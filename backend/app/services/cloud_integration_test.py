"""'Test connection' for cloud integrations — one cheap, read-only,
identity-only API call per vendor (never touches network/VPC resources)
so a saved credential's validity is known immediately. Mirrors
app/services/integration_test.py for the firewall integrations. Never
raises — every SDK exception is caught and turned into (ok, message).
"""
from __future__ import annotations


def test_aws(credentials: dict) -> tuple[bool, str]:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        mode = credentials.get("auth_mode")
        region = credentials.get("region_default") or "us-east-1"
        if mode == "access_key":
            session = boto3.Session(
                aws_access_key_id=credentials["access_key_id"],
                aws_secret_access_key=credentials["secret_access_key"],
                region_name=region,
            )
        elif mode == "role_arn":
            bootstrap = boto3.Session(region_name=region)
            assume_kwargs = {"RoleArn": credentials["role_arn"], "RoleSessionName": "netsphere-test"}
            if credentials.get("external_id"):
                assume_kwargs["ExternalId"] = credentials["external_id"]
            resp = bootstrap.client("sts").assume_role(**assume_kwargs)
            c = resp["Credentials"]
            session = boto3.Session(
                aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"],
                aws_session_token=c["SessionToken"], region_name=region,
            )
        else:
            return False, f"unknown auth_mode: {mode!r}"
        identity = session.client("sts").get_caller_identity()
        return True, f"Connected as {identity['Arn']}"
    except (BotoCoreError, ClientError) as e:
        return False, f"AWS authentication failed: {e}"
    except KeyError as e:
        return False, f"Missing credential field: {e}"


def test_azure(credentials: dict) -> tuple[bool, str]:
    from azure.core.exceptions import AzureError
    from azure.identity import ClientSecretCredential
    from azure.mgmt.subscription import SubscriptionClient

    try:
        credential = ClientSecretCredential(
            tenant_id=credentials["tenant_id"], client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        sub = SubscriptionClient(credential).subscriptions.get(credentials["subscription_id"])
        return True, f"Connected — subscription {sub.display_name} ({sub.state})"
    except AzureError as e:
        return False, f"Azure authentication failed: {e}"
    except KeyError as e:
        return False, f"Missing credential field: {e}"


def test_gcp(credentials: dict) -> tuple[bool, str]:
    import json

    from google.api_core.exceptions import GoogleAPIError
    from google.cloud.compute_v1 import RegionsClient
    from google.oauth2 import service_account

    try:
        info = json.loads(credentials["service_account_json"])
        creds = service_account.Credentials.from_service_account_info(info)
    except (ValueError, KeyError) as e:
        return False, f"Invalid service account JSON: {e}"

    project = info.get("project_id")
    if not project:
        return False, "service_account_json has no project_id"
    try:
        regions = list(RegionsClient(credentials=creds).list(project=project))
        return True, f"Connected — project {project}, {len(regions)} regions visible"
    except GoogleAPIError as e:
        return False, f"GCP authentication failed: {e}"


def test_oci(credentials: dict) -> tuple[bool, str]:
    import oci
    from oci.exceptions import ServiceError

    try:
        config = {
            "user": credentials["user_ocid"], "tenancy": credentials["tenancy_ocid"],
            "fingerprint": credentials["fingerprint"], "key_content": credentials["private_key_pem"],
            "region": credentials.get("region") or "us-ashburn-1",
        }
        user = oci.identity.IdentityClient(config).get_user(user_id=config["user"]).data
        return True, f"Connected as {user.name}"
    except ServiceError as e:
        return False, f"OCI authentication failed: {e.message}"
    except oci.exceptions.InvalidConfig as e:
        return False, f"OCI config invalid: {e}"
    except (oci.exceptions.InvalidPrivateKey, ValueError) as e:
        return False, f"OCI private key invalid: {e}"
    except KeyError as e:
        return False, f"Missing credential field: {e}"


TESTERS = {"aws": test_aws, "azure": test_azure, "gcp": test_gcp, "oci": test_oci}
