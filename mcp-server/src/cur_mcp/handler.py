"""CUR MCP Server - Lambda handler using awslabs.mcp_lambda_handler."""
import os
import boto3
import time

from awslabs.mcp_lambda_handler import MCPLambdaHandler

ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "nci_cur")
ATHENA_TABLE = os.environ.get("ATHENA_TABLE", "nci_cur.cur_data")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT", "")
ATHENA_REGION = os.environ.get("ATHENA_REGION", "eu-central-1")
QUERY_TIMEOUT = 60

athena = boto3.client("athena", region_name=ATHENA_REGION)

mcp_server = MCPLambdaHandler(name="nci-cur-mcp", version="1.0.0")

_last_repair = 0


def _repair_partitions():
    """Run MSCK REPAIR TABLE at most once per hour to pick up new billing periods."""
    global _last_repair
    now = time.time()
    if now - _last_repair < 3600:
        return
    try:
        resp = athena.start_query_execution(
            QueryString=f"MSCK REPAIR TABLE {ATHENA_TABLE}",
            QueryExecutionContext={"Database": ATHENA_DATABASE},
            ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
        )
        qid = resp["QueryExecutionId"]
        for _ in range(15):
            status = athena.get_query_execution(QueryExecutionId=qid)
            state = status["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(2)
        _last_repair = now
    except Exception:
        pass  # Don't block queries if repair fails


def _run_athena_query(sql):
    """Execute Athena query and return results as list of dicts."""
    # Auto-repair partitions to pick up new billing periods
    _repair_partitions()

    resp = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )
    qid = resp["QueryExecutionId"]
    start = time.time()
    while time.time() - start < QUERY_TIMEOUT:
        status = athena.get_query_execution(QueryExecutionId=qid)
        state = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "Unknown")
            raise RuntimeError(f"Query failed: {reason}")
        time.sleep(2)
    else:
        raise TimeoutError(f"Query timed out after {QUERY_TIMEOUT}s")

    rows = []
    paginator = athena.get_paginator("get_query_results")
    headers = None
    for page in paginator.paginate(QueryExecutionId=qid):
        for i, row in enumerate(page["ResultSet"]["Rows"]):
            vals = [c.get("VarCharValue", "") for c in row["Data"]]
            if headers is None:
                headers = vals
            else:
                rows.append(dict(zip(headers, vals)))
    return rows


# --- Classifier ---
def _classify(product_code, usage_type):
    """Map CUR line item to networking cost domain."""
    u = (usage_type or "").lower()
    p = (product_code or "").lower()
    if p == "amazonec2" and "natgateway" in u:
        return "NAT_GATEWAY"
    if p == "amazonvpc" and "vpcendpoint" in u:
        return "VPC_ENDPOINTS"
    if p == "amazonvpc" and "vpn" in u:
        return "VPN"
    if p == "amazonvpc" and "transitgateway" in u:
        return "TRANSIT_GATEWAY"
    if "datatransfer-regional" in u or ("datatransfer" in u and "-az" in u):
        return "INTER_AZ_TRANSFER"
    if "datatransfer" in u and ("-out" in u or "interregion" in u):
        return "CROSS_REGION_TRANSFER"
    if p in ("awselb", "amazonelb", "elasticloadbalancing"):
        return "ELASTIC_LOAD_BALANCER"
    if p == "amazons3" and "datatransfer" in u:
        return "S3_TRANSFER"
    return None


# --- MCP Tools ---

@mcp_server.tool()
def getNetworkingCostBreakdown(account_id: str, start_date: str, end_date: str) -> dict:
    """Get networking cost breakdown by service, region, and AZ for an AWS account.

    Args:
        account_id: AWS account ID (e.g. 123456789012)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Total networking cost, breakdown by service/region/AZ, and top spending resources.
    """
    sql = f"""
    SELECT line_item_product_code AS product_code,
           line_item_usage_type AS usage_type,
           line_item_resource_id AS resource_id,
           product_region_code AS region,
           line_item_availability_zone AS az,
           SUM(line_item_unblended_cost) AS cost,
           SUM(line_item_usage_amount) AS usage_qty,
           pricing_unit AS unit
    FROM {ATHENA_TABLE}
    WHERE line_item_usage_account_id = '{account_id}'
      AND line_item_line_item_type = 'Usage'
      AND cast(line_item_usage_start_date as timestamp) >= timestamp '{start_date}'
      AND cast(line_item_usage_start_date as timestamp) < timestamp '{end_date}'
    GROUP BY 1,2,3,4,5,8
    HAVING SUM(line_item_unblended_cost) > 0
    ORDER BY cost DESC
    """
    rows = _run_athena_query(sql)
    total = 0.0
    by_svc, by_reg, by_az, top = {}, {}, {}, []
    for r in rows:
        d = _classify(r["product_code"], r["usage_type"])
        if not d:
            continue
        c = float(r.get("cost", 0))
        total += c
        by_svc[d] = by_svc.get(d, 0) + c
        reg = r.get("region", "")
        by_reg[reg] = by_reg.get(reg, 0) + c
        az = r.get("az", "")
        if az:
            by_az[az] = by_az.get(az, 0) + c
        top.append({"resource_id": r["resource_id"], "service": d,
                     "region": reg, "cost": round(c, 4),
                     "usage_type": r["usage_type"],
                     "usage_qty": float(r.get("usage_qty", 0)),
                     "unit": r.get("unit", "")})
    return {"total_networking_cost": round(total, 2),
            "by_service": {k: round(v, 2) for k, v in by_svc.items()},
            "by_region": {k: round(v, 2) for k, v in by_reg.items()},
            "by_az": {k: round(v, 2) for k, v in by_az.items()},
            "top_resources": top[:20]}


@mcp_server.tool()
def getResourceCostDetail(resource_id: str, start_date: str, end_date: str) -> dict:
    """Get detailed cost breakdown for a specific AWS networking resource with all CUR dimensions.
    Works for NAT Gateway, Transit Gateway, VPC Endpoints, Load Balancers, etc.

    Args:
        resource_id: AWS resource ID (e.g. nat-01ecb538bcedc85f4, tgw-attach-xxx, vpce-xxx)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Detailed cost breakdown by UsageType, Operation, region, transfer direction,
        from/to locations with effective cost (unblended + reservation + savings plan).
    """
    sql = f"""
    SELECT
        line_item_product_code AS product_code,
        product_region_code AS region,
        line_item_usage_account_id AS account_id,
        line_item_resource_id AS resource_id,
        line_item_usage_type AS usage_type,
        line_item_operation AS operation,
        line_item_line_item_type AS line_item_type,
        line_item_line_item_description AS description,
        product_product_family AS product_family,
        product_from_location AS from_location,
        product_from_region_code AS from_region,
        product_to_location AS to_location,
        product_to_region_code AS to_region,
        line_item_availability_zone AS az,
        pricing_unit AS unit,
        SUM(line_item_usage_amount) AS usage_qty,
        (SUM(line_item_unblended_cost)
         + SUM(COALESCE(reservation_effective_cost, 0))
         + SUM(COALESCE(savings_plan_savings_plan_effective_cost, 0))) AS effective_cost,
        SUM(line_item_net_unblended_cost) AS net_cost
    FROM {ATHENA_TABLE}
    WHERE line_item_resource_id LIKE '%{resource_id}%'
      AND cast(line_item_usage_start_date as timestamp) >= timestamp '{start_date}'
      AND cast(line_item_usage_start_date as timestamp) < timestamp '{end_date}'
      AND line_item_line_item_type IN ('DiscountedUsage', 'SavingsPlanCoveredUsage', 'Usage')
    GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
    ORDER BY effective_cost DESC
    """
    rows = _run_athena_query(sql)
    breakdown = []
    total_effective = 0.0
    total_net = 0.0
    for r in rows:
        eff = float(r.get("effective_cost", 0) or 0)
        net = float(r.get("net_cost", 0) or 0)
        total_effective += eff
        total_net += net
        breakdown.append({
            "product_code": r.get("product_code", ""),
            "region": r.get("region", ""),
            "usage_type": r.get("usage_type", ""),
            "operation": r.get("operation", ""),
            "line_item_type": r.get("line_item_type", ""),
            "description": r.get("description", ""),
            "product_family": r.get("product_family", ""),
            "from_location": r.get("from_location", ""),
            "from_region": r.get("from_region", ""),
            "to_location": r.get("to_location", ""),
            "to_region": r.get("to_region", ""),
            "az": r.get("az", ""),
            "unit": r.get("unit", ""),
            "usage_qty": float(r.get("usage_qty", 0) or 0),
            "effective_cost": round(eff, 4),
            "net_cost": round(net, 4),
        })
    return {
        "resource_id": resource_id,
        "total_effective_cost": round(total_effective, 2),
        "total_net_cost": round(total_net, 2),
        "breakdown": breakdown,
    }


@mcp_server.tool()
def detectCostAnomalies(account_id: str, start_date: str, end_date: str,
                        baseline_start: str, baseline_end: str) -> dict:
    """Compare current networking costs against a baseline period to find cost spikes.

    Args:
        account_id: AWS account ID
        start_date: Current period start date (YYYY-MM-DD)
        end_date: Current period end date (YYYY-MM-DD)
        baseline_start: Baseline period start date (YYYY-MM-DD)
        baseline_end: Baseline period end date (YYYY-MM-DD)

    Returns:
        List of resources with cost anomalies, percentage increase, and likely cause.
    """
    def _costs(sd, ed):
        sql = f"""
        SELECT line_item_resource_id AS rid, line_item_product_code AS pc,
               line_item_usage_type AS ut, SUM(line_item_unblended_cost) AS cost
        FROM {ATHENA_TABLE}
        WHERE line_item_usage_account_id = '{account_id}'
          AND line_item_line_item_type = 'Usage'
          AND cast(line_item_usage_start_date as timestamp) >= timestamp '{sd}'
          AND cast(line_item_usage_start_date as timestamp) < timestamp '{ed}'
        GROUP BY 1,2,3 HAVING SUM(line_item_unblended_cost) > 0
        """
        res = {}
        for r in _run_athena_query(sql):
            d = _classify(r["pc"], r["ut"])
            if not d:
                continue
            rid = r["rid"]
            c = float(r.get("cost", 0))
            if rid in res:
                res[rid]["cost"] += c
            else:
                res[rid] = {"cost": c, "service": d}
        return res

    current = _costs(start_date, end_date)
    baseline = _costs(baseline_start, baseline_end)
    anomalies = []
    for rid, cur in current.items():
        base = baseline.get(rid)
        if base and base["cost"] > 0:
            pct = ((cur["cost"] - base["cost"]) / base["cost"]) * 100
            if pct > 20:
                anomalies.append({"resource_id": rid, "service": cur["service"],
                                  "current_cost": round(cur["cost"], 2),
                                  "baseline_cost": round(base["cost"], 2),
                                  "percentage_increase": round(pct, 1)})
        elif cur["cost"] > 1.0:
            anomalies.append({"resource_id": rid, "service": cur["service"],
                              "current_cost": round(cur["cost"], 2),
                              "baseline_cost": 0, "percentage_increase": None,
                              "likely_cause": "New resource"})
    anomalies.sort(key=lambda x: x["current_cost"], reverse=True)
    return {"anomalies": anomalies}


@mcp_server.tool()
def getTopNetworkingSpenders(account_id: str, start_date: str, end_date: str, limit: int = 10) -> dict:
    """Get top N resources by networking cost.

    Args:
        account_id: AWS account ID
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        limit: Number of top resources to return (default 10)

    Returns:
        Top N networking resources sorted by cost descending.
    """
    result = getNetworkingCostBreakdown(account_id, start_date, end_date)
    return {"top_spenders": result["top_resources"][:limit],
            "total_networking_cost": result["total_networking_cost"]}


@mcp_server.tool()
def getCostTrend(account_id: str, start_date: str, end_date: str, granularity: str = "daily") -> dict:
    """Get hourly, daily, or weekly cost trend for networking services.

    Args:
        account_id: AWS account ID
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        granularity: 'hourly', 'daily', or 'weekly'

    Returns:
        Time-series cost data for networking services at the requested granularity.
    """
    trunc = {"hourly": "hour", "daily": "day", "weekly": "week"}.get(granularity, "day")
    sql = f"""
    SELECT date_trunc('{trunc}', line_item_usage_start_date) AS period,
           line_item_product_code AS pc, line_item_usage_type AS ut,
           SUM(line_item_unblended_cost) AS cost
    FROM {ATHENA_TABLE}
    WHERE line_item_usage_account_id = '{account_id}'
      AND line_item_line_item_type = 'Usage'
      AND cast(line_item_usage_start_date as timestamp) >= timestamp '{start_date}'
      AND cast(line_item_usage_start_date as timestamp) < timestamp '{end_date}'
    GROUP BY 1,2,3 HAVING SUM(line_item_unblended_cost) > 0
    ORDER BY period ASC
    """
    rows = _run_athena_query(sql)
    trend = {}
    for r in rows:
        d = _classify(r["pc"], r["ut"])
        if not d:
            continue
        p = str(r.get("period", ""))
        c = float(r.get("cost", 0))
        if p not in trend:
            trend[p] = {"period": p, "total": 0, "by_service": {}}
        trend[p]["total"] += c
        trend[p]["by_service"][d] = trend[p]["by_service"].get(d, 0) + c
    result = []
    for td in trend.values():
        td["total"] = round(td["total"], 2)
        td["by_service"] = {k: round(v, 2) for k, v in td["by_service"].items()}
        result.append(td)
    return {"trend": result, "granularity": granularity}


@mcp_server.tool()
def getCURDataRange() -> dict:
    """Get the exact time range covered by the CUR data currently available in Athena.

    Returns:
        Earliest and latest usage timestamps in the CUR data, and total row count.
    """
    sql = f"""
    SELECT
        MIN(line_item_usage_start_date) AS earliest_start,
        MAX(line_item_usage_end_date) AS latest_end,
        COUNT(*) AS total_rows
    FROM {ATHENA_TABLE}
    """
    rows = _run_athena_query(sql)
    if rows:
        return {
            "earliest_usage_start": rows[0].get("earliest_start", ""),
            "latest_usage_end": rows[0].get("latest_end", ""),
            "total_rows": int(rows[0].get("total_rows", 0) or 0),
        }
    return {"earliest_usage_start": "", "latest_usage_end": "", "total_rows": 0}


def lambda_handler(event, context):
    """Lambda entry point."""
    return mcp_server.handle_request(event, context)
