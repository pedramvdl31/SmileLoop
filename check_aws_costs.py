#!/usr/bin/env python3
"""
Quick AWS Cost Explorer script.
Shows your top cost drivers for the last 30 days, grouped by service.

Usage:
    # Make sure your AWS credentials are set (env vars or ~/.aws/credentials)
    python check_aws_costs.py

    # Or specify a profile:
    AWS_PROFILE=myprofile python check_aws_costs.py
"""

import json
import sys
from datetime import datetime, timedelta

try:
    import boto3
except ImportError:
    print("ERROR: boto3 not installed. Run: pip install boto3")
    sys.exit(1)


def get_cost_breakdown(days=30):
    """Pull cost-by-service for the last N days."""
    client = boto3.client("ce", region_name="us-east-1")

    end = datetime.utcnow().date()
    start = end - timedelta(days=days)

    resp = client.get_cost_and_usage(
        TimePeriod={"Start": str(start), "End": str(end)},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    # Flatten results
    costs = []
    for period in resp["ResultsByTime"]:
        time_range = f"{period['TimePeriod']['Start']} → {period['TimePeriod']['End']}"
        for group in period["Groups"]:
            service = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            unit = group["Metrics"]["UnblendedCost"]["Unit"]
            if amount > 0.001:
                costs.append((amount, service, unit, time_range))

    costs.sort(reverse=True)
    return costs


def get_total(days=30):
    """Get total spend for the last N days."""
    client = boto3.client("ce", region_name="us-east-1")

    end = datetime.utcnow().date()
    start = end - timedelta(days=days)

    resp = client.get_cost_and_usage(
        TimePeriod={"Start": str(start), "End": str(end)},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )

    total = 0
    for period in resp["ResultsByTime"]:
        total += float(period["Total"]["UnblendedCost"]["Amount"])
    return total


def main():
    print("=" * 60)
    print("  AWS Cost Breakdown — Last 30 Days")
    print("=" * 60)
    print()

    try:
        total = get_total(30)
        costs = get_cost_breakdown(30)
    except Exception as e:
        print(f"ERROR: {e}")
        print()
        print("Make sure your AWS credentials are configured:")
        print("  export AWS_ACCESS_KEY_ID=...")
        print("  export AWS_SECRET_ACCESS_KEY=...")
        print()
        print("Or: aws configure")
        sys.exit(1)

    print(f"  TOTAL: ${total:.2f}")
    print()
    print(f"  {'Service':<45} {'Cost':>10}")
    print("  " + "-" * 56)

    for amount, service, unit, time_range in costs:
        pct = (amount / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {service:<45} ${amount:>8.2f}  {pct:4.1f}%  {bar}")

    print()
    print("  " + "-" * 56)
    print(f"  {'TOTAL':<45} ${total:>8.2f}")
    print()

    # Also show last 3 months for trend
    print("=" * 60)
    print("  Monthly Trend (Last 3 Months)")
    print("=" * 60)
    print()

    client = boto3.client("ce", region_name="us-east-1")
    end = datetime.utcnow().date().replace(day=1)
    start = (end - timedelta(days=90)).replace(day=1)

    resp = client.get_cost_and_usage(
        TimePeriod={"Start": str(start), "End": str(end)},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )

    for period in resp["ResultsByTime"]:
        month = period["TimePeriod"]["Start"]
        amount = float(period["Total"]["UnblendedCost"]["Amount"])
        print(f"  {month}  ${amount:.2f}")

    print()


if __name__ == "__main__":
    main()
