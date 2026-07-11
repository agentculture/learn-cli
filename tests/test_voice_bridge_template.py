"""Tests for ``infra/template.yaml`` — the Nova Sonic 2 voice-bridge SAM stack.

Mirrors league-of-agents-platform's ``tests/test_lambda_template.py`` approach:
no AWS is touched — the template is parsed as *plain YAML* (long-form
``Fn::Sub``/``Ref``/``Fn::GetAtt`` intrinsics only, never ``!Sub`` tags, so any
standard loader can inspect it) and its shape is asserted: the WebSocket API,
the single arm64 Lambda, the capacity-cap Parameters cross-checked against the
Python source constants, and the Budgets alarm pinned to the monthly ceiling.
``sam validate`` runs only when the CLI happens to be installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from voice_bridge import config as bridge_config

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "infra" / "template.yaml"

_EXPECTED_RESOURCES: dict[str, str] = {
    "WebSocketApi": "AWS::ApiGatewayV2::Api",
    "WebSocketStage": "AWS::ApiGatewayV2::Stage",
    "ConnectRoute": "AWS::ApiGatewayV2::Route",
    "DisconnectRoute": "AWS::ApiGatewayV2::Route",
    "DefaultRoute": "AWS::ApiGatewayV2::Route",
    "BridgeIntegration": "AWS::ApiGatewayV2::Integration",
    "WebSocketInvokePermission": "AWS::Lambda::Permission",
    "BridgeFunction": "AWS::Serverless::Function",
    "BridgeFunctionLogGroup": "AWS::Logs::LogGroup",
    "VoiceSessionsTable": "AWS::DynamoDB::Table",
    "MonthlyBudget": "AWS::Budgets::Budget",
}


@pytest.fixture(scope="module")
def template() -> dict[str, Any]:
    """Parse the template with a plain YAML loader (the long-form-intrinsics proof)."""
    with _TEMPLATE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_template_file_exists() -> None:
    assert _TEMPLATE_PATH.is_file()


def test_template_parses_as_plain_yaml(template: dict[str, Any]) -> None:
    assert isinstance(template, dict)
    assert template["AWSTemplateFormatVersion"] == "2010-09-09"
    assert template["Transform"] == "AWS::Serverless-2016-10-31"


def test_template_contains_no_shortform_intrinsics() -> None:
    """Belt and braces on top of the safe_load fixture: no ``!Sub``-style tags at all."""
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    for tag in ("!Sub", "!Ref", "!GetAtt", "!Join", "!If"):
        assert tag not in text


def test_template_declares_exactly_the_expected_resources(template: dict[str, Any]) -> None:
    resources = template["Resources"]
    assert set(resources.keys()) == set(_EXPECTED_RESOURCES.keys())
    for logical_id, expected_type in _EXPECTED_RESOURCES.items():
        assert resources[logical_id]["Type"] == expected_type


def test_lambda_is_python312_arm64(template: dict[str, Any]) -> None:
    """arm64 + python3.12, set once in Globals — league's convention, ~20% cheaper GB-s."""
    function_defaults = template["Globals"]["Function"]
    assert function_defaults["Runtime"] == "python3.12"
    assert function_defaults["Architectures"] == ["arm64"]
    assert function_defaults["Tracing"] == "Disabled"


def test_lambda_timeout_exceeds_the_default_session_cap(template: dict[str, Any]) -> None:
    """The Lambda timeout is the backstop circuit breaker over MaxSessionSeconds.

    The session holder self-terminates at MAX_SESSION_SECONDS; the function
    timeout must sit above the default cap (with grace for stream teardown)
    or every max-length session would be killed mid-teardown.
    """
    timeout = template["Globals"]["Function"]["Timeout"]
    default_cap = template["Parameters"]["MaxSessionSeconds"]["Default"]
    assert timeout > default_cap
    assert timeout <= 900  # Lambda's own hard maximum


def test_zero_idle_cost(template: dict[str, Any]) -> None:
    """No provisioned concurrency, no always-on resource anywhere in the stack."""
    text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "ProvisionedConcurrency" not in text
    for resource in template["Resources"].values():
        assert not resource["Type"].startswith("AWS::EC2::")
        assert not resource["Type"].startswith("AWS::ECS::")


def test_monthly_budget_parameter_matches_the_python_ceiling(template: dict[str, Any]) -> None:
    parameter = template["Parameters"]["MonthlyBudgetUsd"]
    assert parameter["Default"] == bridge_config.DEFAULT_MONTHLY_BUDGET_USD == 20


def test_budget_alert_email_has_no_default(template: dict[str, Any]) -> None:
    """The operator must supply a real address at deploy time — league's posture."""
    parameter = template["Parameters"]["BudgetAlertEmail"]
    assert parameter["Type"] == "String"
    assert "Default" not in parameter


def test_budget_resource_is_wired_to_the_ceiling_parameter(template: dict[str, Any]) -> None:
    budget = template["Resources"]["MonthlyBudget"]["Properties"]["Budget"]
    assert budget["BudgetLimit"]["Amount"] == {"Ref": "MonthlyBudgetUsd"}
    assert budget["BudgetLimit"]["Unit"] == "USD"
    assert budget["BudgetType"] == "COST"
    assert budget["TimeUnit"] == "MONTHLY"


def test_budget_notifies_at_80_actual_and_100_forecast(template: dict[str, Any]) -> None:
    subscriptions = template["Resources"]["MonthlyBudget"]["Properties"][
        "NotificationsWithSubscribers"
    ]
    seen = {
        (entry["Notification"]["NotificationType"], entry["Notification"]["Threshold"])
        for entry in subscriptions
    }
    assert seen == {("ACTUAL", 80), ("FORECASTED", 100)}
    for entry in subscriptions:
        addresses = [sub["Address"] for sub in entry["Subscribers"]]
        assert {"Ref": "BudgetAlertEmail"} in addresses


def test_voice_token_secret_is_noecho_defaulting_empty(template: dict[str, Any]) -> None:
    """Empty default means the bridge refuses every connection — disabled until t16 mints."""
    parameter = template["Parameters"]["VoiceTokenSecretValue"]
    assert parameter["Type"] == "String"
    assert parameter["NoEcho"] is True
    assert parameter["Default"] == ""


def test_capacity_parameter_defaults_match_the_python_source(template: dict[str, Any]) -> None:
    """The template's caps and voice_bridge.config must never drift apart (league's guard)."""
    parameters = template["Parameters"]
    assert parameters["MaxSessionSeconds"]["Default"] == bridge_config.DEFAULT_MAX_SESSION_SECONDS
    assert (
        parameters["MaxConcurrentVoiceSessions"]["Default"]
        == bridge_config.DEFAULT_MAX_CONCURRENT_VOICE_SESSIONS
    )
    assert parameters["NovaSonicModelId"]["Default"] == bridge_config.NOVA_SONIC_MODEL_ID


def test_websocket_api_is_a_websocket_api(template: dict[str, Any]) -> None:
    api = template["Resources"]["WebSocketApi"]["Properties"]
    assert api["ProtocolType"] == "WEBSOCKET"
    assert api["RouteSelectionExpression"] == "$request.body.action"


def test_all_three_routes_target_the_single_integration(template: dict[str, Any]) -> None:
    route_keys = set()
    for logical_id in ("ConnectRoute", "DisconnectRoute", "DefaultRoute"):
        route = template["Resources"][logical_id]["Properties"]
        route_keys.add(route["RouteKey"])
        assert route["ApiId"] == {"Ref": "WebSocketApi"}
        assert route["AuthorizationType"] == "NONE"
        assert route["Target"] == {"Fn::Sub": "integrations/${BridgeIntegration}"}
    assert route_keys == {"$connect", "$disconnect", "$default"}


def test_stage_throttling_is_a_cost_circuit_breaker(template: dict[str, Any]) -> None:
    stage = template["Resources"]["WebSocketStage"]["Properties"]
    assert stage["ApiId"] == {"Ref": "WebSocketApi"}
    assert stage["AutoDeploy"] is True
    settings = stage["DefaultRouteSettings"]
    assert settings["ThrottlingBurstLimit"] > 0
    assert settings["ThrottlingRateLimit"] > 0


def test_bridge_function_env_names_match_python_source_constants(
    template: dict[str, Any],
) -> None:
    """Env-var *names* come from voice_bridge.config so template and code cannot drift."""
    env = template["Resources"]["BridgeFunction"]["Properties"]["Environment"]["Variables"]
    assert env[bridge_config.VOICE_TOKEN_SECRET_ENV] == {"Ref": "VoiceTokenSecretValue"}
    assert env[bridge_config.SESSIONS_TABLE_ENV] == {"Ref": "VoiceSessionsTable"}
    assert env[bridge_config.MAX_SESSION_SECONDS_ENV] == {"Ref": "MaxSessionSeconds"}
    assert env[bridge_config.MAX_CONCURRENT_SESSIONS_ENV] == {"Ref": "MaxConcurrentVoiceSessions"}
    assert env[bridge_config.MODEL_ID_ENV] == {"Ref": "NovaSonicModelId"}
    assert bridge_config.SELF_FUNCTION_NAME_ENV in env
    assert bridge_config.CALLBACK_URL_ENV in env


def _statements(policies: list[Any]) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for policy in policies:
        if isinstance(policy, dict) and "Statement" in policy:
            statements.extend(policy["Statement"])
    return statements


def _actions(statement: dict[str, Any]) -> list[str]:
    actions = statement["Action"]
    return [actions] if isinstance(actions, str) else list(actions)


def test_bridge_function_may_open_the_bidirectional_stream(template: dict[str, Any]) -> None:
    """Least privilege: exactly InvokeModelWithBidirectionalStream on the Sonic model."""
    policies = template["Resources"]["BridgeFunction"]["Properties"]["Policies"]
    bedrock = [
        statement
        for statement in _statements(policies)
        if any(action.startswith("bedrock:") for action in _actions(statement))
    ]
    assert len(bedrock) == 1
    assert _actions(bedrock[0]) == ["bedrock:InvokeModelWithBidirectionalStream"]
    resource = bedrock[0]["Resource"]
    resource_str = resource.get("Fn::Sub", "") if isinstance(resource, dict) else str(resource)
    assert "NovaSonicModelId" in resource_str


def test_bridge_function_may_post_to_connections(template: dict[str, Any]) -> None:
    policies = template["Resources"]["BridgeFunction"]["Properties"]["Policies"]
    manage = [
        statement
        for statement in _statements(policies)
        if "execute-api:ManageConnections" in _actions(statement)
    ]
    assert len(manage) == 1
    resource_str = manage[0]["Resource"]["Fn::Sub"]
    assert "@connections" in resource_str


def test_bridge_function_may_async_invoke_itself(template: dict[str, Any]) -> None:
    """The session holder is the same function self-invoked async (one-Lambda design)."""
    policies = template["Resources"]["BridgeFunction"]["Properties"]["Policies"]
    invoke = [
        statement
        for statement in _statements(policies)
        if "lambda:InvokeFunction" in _actions(statement)
    ]
    assert len(invoke) == 1
    resource_str = invoke[0]["Resource"]["Fn::Sub"]
    assert "learn-voice-${StageName}-bridge" in resource_str
    function_name = template["Resources"]["BridgeFunction"]["Properties"]["FunctionName"]
    assert function_name == {"Fn::Sub": "learn-voice-${StageName}-bridge"}


def test_bridge_function_has_crud_on_the_sessions_table(template: dict[str, Any]) -> None:
    policies = template["Resources"]["BridgeFunction"]["Properties"]["Policies"]
    crud_refs = [
        policy["DynamoDBCrudPolicy"]["TableName"]
        for policy in policies
        if isinstance(policy, dict) and "DynamoDBCrudPolicy" in policy
    ]
    assert crud_refs == [{"Ref": "VoiceSessionsTable"}]


def test_sessions_table_uses_pk_sk_on_demand_and_ttl(template: dict[str, Any]) -> None:
    """League's single-table PK/SK convention; TTL garbage-collects stale rows for free."""
    table = template["Resources"]["VoiceSessionsTable"]["Properties"]
    assert table["BillingMode"] == "PAY_PER_REQUEST"
    key_schema = {entry["AttributeName"]: entry["KeyType"] for entry in table["KeySchema"]}
    assert key_schema == {"PK": "HASH", "SK": "RANGE"}
    ttl = table["TimeToLiveSpecification"]
    assert ttl == {"AttributeName": "expires_at", "Enabled": True}


def test_log_group_has_bounded_retention(template: dict[str, Any]) -> None:
    log_group = template["Resources"]["BridgeFunctionLogGroup"]["Properties"]
    assert isinstance(log_group["RetentionInDays"], int)
    assert 0 < log_group["RetentionInDays"] <= 30


def test_invoke_permission_covers_the_websocket_api(template: dict[str, Any]) -> None:
    permission = template["Resources"]["WebSocketInvokePermission"]["Properties"]
    assert permission["Action"] == "lambda:InvokeFunction"
    assert permission["Principal"] == "apigateway.amazonaws.com"
    assert "WebSocketApi" in permission["SourceArn"]["Fn::Sub"]


def test_outputs_expose_the_wss_url(template: dict[str, Any]) -> None:
    outputs = template["Outputs"]
    assert outputs["WebSocketUrl"]["Value"]["Fn::Sub"].startswith("wss://")
    assert outputs["VoiceSessionsTableName"]["Value"] == {"Ref": "VoiceSessionsTable"}


@pytest.mark.skipif(shutil.which("sam") is None, reason="AWS SAM CLI not installed")
def test_sam_validate_if_sam_cli_present() -> None:
    """Bonus sanity check only — deploying is a later, supervised task."""
    result = subprocess.run(
        ["sam", "validate", "--region", "us-east-1", "--template-file", str(_TEMPLATE_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
