"""Tests for A2A trust scoring."""

from __future__ import annotations

from agenticapi.interface.a2a.trust import TrustPolicy, TrustScorer


class TestTrustPolicy:
    def test_defaults(self) -> None:
        policy = TrustPolicy()
        assert policy.initial_trust == 0.5
        assert policy.min_trust_for_read == 0.3
        assert policy.min_trust_for_write == 0.8
        assert policy.decay_per_failure == 0.1
        assert policy.gain_per_success == 0.05


class TestTrustScorer:
    def test_unknown_agent_gets_initial_trust(self) -> None:
        scorer = TrustScorer()
        assert scorer.get_score("unknown") == 0.5

    def test_record_success_increases_score(self) -> None:
        scorer = TrustScorer()
        new = scorer.record_success("agent-1")
        assert new == 0.55
        assert scorer.get_score("agent-1") == 0.55

    def test_record_failure_decreases_score(self) -> None:
        scorer = TrustScorer()
        new = scorer.record_failure("agent-1")
        assert new == 0.4
        assert scorer.get_score("agent-1") == 0.4

    def test_score_capped_at_1(self) -> None:
        scorer = TrustScorer(policy=TrustPolicy(initial_trust=0.98, gain_per_success=0.05))
        new = scorer.record_success("agent-1")
        assert new == 1.0

    def test_score_capped_at_0(self) -> None:
        scorer = TrustScorer(policy=TrustPolicy(initial_trust=0.05, decay_per_failure=0.1))
        new = scorer.record_failure("agent-1")
        assert new == 0.0

    def test_can_read_with_default_initial(self) -> None:
        scorer = TrustScorer()
        # initial_trust=0.5 >= min_trust_for_read=0.3
        assert scorer.can_read("agent-1") is True

    def test_can_write_with_default_initial(self) -> None:
        scorer = TrustScorer()
        # initial_trust=0.5 < min_trust_for_write=0.8
        assert scorer.can_write("agent-1") is False

    def test_can_write_after_successes(self) -> None:
        scorer = TrustScorer(policy=TrustPolicy(gain_per_success=0.1))
        for _ in range(4):
            scorer.record_success("agent-1")
        # 0.5 + 4*0.1 = 0.9 >= 0.8
        assert scorer.can_write("agent-1") is True

    def test_policy_property(self) -> None:
        policy = TrustPolicy(initial_trust=0.7)
        scorer = TrustScorer(policy=policy)
        assert scorer.policy is policy
