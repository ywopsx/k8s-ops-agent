from pathlib import Path

from preflight.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_finds_planted_issues_and_fails(capsys):
    code = main(["--target-version", "1.33", "--from-dir", str(FIXTURES / "snapshot"),
                 "--cni-baseline", str(FIXTURES / "cni-baseline.json")])
    out = capsys.readouterr().out
    assert code == 1
    for expected in ["Deployment/shop/legacy-batch", "PodDisruptionBudget/shop/legacy-batch",
                     "Pod/shop/debug-shell", "Node/ip-10-0-1-10", "FlowSchema/custom-fs",
                     "AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG", "Service/shop/storefront", "Ingress/shop/storefront-web",
                     "TargetGroupBinding/shop/legacy-tg", "Deployment/shop/checkout"]:
        assert expected in out
    assert "order-api" not in out  # 역할 라벨 + replica 3 → 문제 없음


def test_fail_on_never_returns_zero(capsys):
    assert main(["--target-version", "1.33", "--from-dir", str(FIXTURES / "snapshot"), "--fail-on", "never"]) == 0


def test_save_snapshot_roundtrip(tmp_path, capsys):
    main(["--target-version", "1.33", "--from-dir", str(FIXTURES / "snapshot"),
          "--save-snapshot", str(tmp_path), "--fail-on", "never"])
    assert (tmp_path / "deployments.json").exists()
