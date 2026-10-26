"""Real AWS adapter. Phase 3 (see providers/README.md history in
ARCHITECTURE.md §3): boto3 + either a long-lived access key or an
assumable IAM role, sourced from a CloudIntegration credential
(app/models/cloud_integration.py) rather than `cloud_accounts.credential_ref`
directly — that column still exists as a pointer for anyone reading the DB,
but the actual secret material lives only in the encrypted
`cloud_integrations.credentials_ciphertext`.

Only this file may import boto3 — see providers/base.py's rule.
"""
from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.providers.base import CloudProvider, DiscoveredNetwork, DiscoveredSubnet


class AWSProvider(CloudProvider):
    provider_name = "aws"

    def _session(self) -> boto3.Session:
        if not self.credentials:
            raise NotImplementedError(
                f"AWSProvider requires a configured, active AWS integration for account "
                f"{self.account_identifier} (Integrations tab) — none found. Use "
                "providers.mock.aws.MockAWSProvider for local development and demos.",
            )
        region = self.region or self.credentials.get("region_default") or "us-east-1"
        mode = self.credentials.get("auth_mode")

        if mode == "access_key":
            return boto3.Session(
                aws_access_key_id=self.credentials["access_key_id"],
                aws_secret_access_key=self.credentials["secret_access_key"],
                region_name=region,
            )
        if mode == "role_arn":
            bootstrap = boto3.Session(region_name=region)
            sts = bootstrap.client("sts")
            assume_kwargs = {"RoleArn": self.credentials["role_arn"], "RoleSessionName": "netsphere-discovery"}
            if self.credentials.get("external_id"):
                assume_kwargs["ExternalId"] = self.credentials["external_id"]
            resp = sts.assume_role(**assume_kwargs)
            creds = resp["Credentials"]
            return boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=region,
            )
        raise NotImplementedError(f"unknown AWS auth_mode: {mode!r}")

    def discover_networks(self) -> list[DiscoveredNetwork]:
        session = self._session()
        ec2 = session.client("ec2")
        try:
            vpcs = ec2.describe_vpcs()["Vpcs"]
        except (BotoCoreError, ClientError) as e:
            raise RuntimeError(f"AWS describe_vpcs failed: {e}") from e

        networks: list[DiscoveredNetwork] = []
        for vpc in vpcs:
            tags = {t["Key"]: t["Value"] for t in vpc.get("Tags", [])}
            name = tags.get("Name", vpc["VpcId"])
            try:
                subnets_resp = ec2.describe_subnets(
                    Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}],
                )["Subnets"]
            except (BotoCoreError, ClientError) as e:
                raise RuntimeError(f"AWS describe_subnets failed for {vpc['VpcId']}: {e}") from e

            subnets = [
                DiscoveredSubnet(
                    external_id=s["SubnetId"],
                    cidr=s["CidrBlock"],
                    availability_zone=s.get("AvailabilityZone"),
                    name=next((t["Value"] for t in s.get("Tags", []) if t["Key"] == "Name"), s["SubnetId"]),
                )
                for s in subnets_resp
            ]
            networks.append(DiscoveredNetwork(
                external_id=vpc["VpcId"], name=name, cidr=vpc.get("CidrBlock", ""),
                region=session.region_name, account_identifier=self.account_identifier,
                subnets=subnets, tags=tags,
            ))
        return networks
