import json

from tools import deploy_check


def test_classify_readiness_requires_exact_service_marker():
    ready = json.dumps({"service": "personnel-system", "status": "ready", "schema": 6}).encode()
    assert deploy_check.classify_response(200, ready) == deploy_check.READY
    assert deploy_check.classify_response(200, b"<html>login</html>") == deploy_check.FOREIGN
    assert deploy_check.classify_response(200, b'{"service":"other","status":"ready","schema":6}') == deploy_check.FOREIGN
    assert deploy_check.classify_response(503, b'{"service":"personnel-system","status":"unavailable"}') == deploy_check.UNAVAILABLE


def test_host_python_contract_rejects_store_alias_and_wrong_wheel_abi():
    assert deploy_check.host_python_problem((3, 11, 9), False)
    assert deploy_check.host_python_problem((3, 10, 9), True, 64, "cp311")
    assert deploy_check.host_python_problem((3, 11, 9), True, 32, "cp311")
    assert deploy_check.host_python_problem((3, 11, 9), True, 64, "cp311") is None


def test_platform_and_port_contract():
    assert deploy_check.platform_problem("Windows", "AMD64", "10.0") is None
    assert deploy_check.platform_problem("Windows", "x86", "10.0")
    assert deploy_check.platform_problem("Linux", "x86_64")
    assert deploy_check.parse_port("5050") == 5050
    for invalid in ("0", "65536", "abc"):
        try:
            deploy_check.parse_port(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid port {invalid}")
