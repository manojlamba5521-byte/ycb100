"""Task-admission contracts for public and sealed ConsequenceBench corpus review.

The module records review evidence; it does not simulate human reviewers or
turn developer-authored approval into independent admission.  Any caller that
cannot supply distinct reviewer records receives a fail-closed result.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from benchmarks.yuvin_consequencebench_100.adaptive_causal.contracts import sha256_payload


TASK_REVIEW_SCHEMA_VERSION = "ycb100.acc.task_review.v1"
TASK_ADMISSION_SCHEMA_VERSION = "ycb100.acc.task_admission.v1"
ADMISSION_CAMPAIGN_SCHEMA_VERSION = "ycb100.acc.admission_campaign.v1"
REVIEW_DISPOSITIONS = frozenset({"admit", "reject", "ambiguous"})
REVIEWER_ROLES = frozenset({"domain_reviewer", "adjudicator"})


def _identifier(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 256:
        raise ValueError(field_name + " is required")
    return normalized


def _digest(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith("sha256:") or len(normalized) != 71:
        raise ValueError(field_name + " must be a sha256 digest")
    return normalized


@dataclass(frozen=True)
class TaskReviewV1:
    template_hash: str
    reviewer_id: str
    reviewer_role: str
    disposition: str
    reason_hash: str
    review_hash: str = ""
    schema_version: str = TASK_REVIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TASK_REVIEW_SCHEMA_VERSION:
            raise ValueError("task review schema version mismatch")
        object.__setattr__(self, "template_hash", _digest(self.template_hash, "template_hash"))
        object.__setattr__(self, "reviewer_id", _identifier(self.reviewer_id, "reviewer_id"))
        if self.reviewer_role not in REVIEWER_ROLES:
            raise ValueError("reviewer_role is invalid")
        if self.disposition not in REVIEW_DISPOSITIONS:
            raise ValueError("review disposition is invalid")
        object.__setattr__(self, "reason_hash", _digest(self.reason_hash, "reason_hash"))
        expected = sha256_payload(self._payload())
        if self.review_hash and self.review_hash != expected:
            raise ValueError("review_hash mismatch")
        object.__setattr__(self, "review_hash", expected)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "template_hash": self.template_hash,
            "reviewer_id": self.reviewer_id,
            "reviewer_role": self.reviewer_role,
            "disposition": self.disposition,
            "reason_hash": self.reason_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "review_hash": self.review_hash}


@dataclass(frozen=True)
class TaskAdmissionV1:
    first_review: TaskReviewV1
    second_review: TaskReviewV1
    adjudication: TaskReviewV1 | None = None
    admission_hash: str = ""
    schema_version: str = TASK_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TASK_ADMISSION_SCHEMA_VERSION:
            raise ValueError("task admission schema version mismatch")
        if not isinstance(self.first_review, TaskReviewV1) or not isinstance(self.second_review, TaskReviewV1):
            raise ValueError("task admission requires two canonical reviews")
        first, second = self.first_review, self.second_review
        if first.reviewer_role != "domain_reviewer" or second.reviewer_role != "domain_reviewer":
            raise ValueError("first two reviews must be domain_reviewer reviews")
        if first.template_hash != second.template_hash:
            raise ValueError("dual reviews must bind the same template")
        if first.reviewer_id == second.reviewer_id:
            raise ValueError("dual reviews must be independent reviewers")
        disagreed = first.disposition != second.disposition
        adjudication = self.adjudication
        if disagreed:
            if not isinstance(adjudication, TaskReviewV1):
                raise ValueError("disagreeing dual reviews require adjudication")
            if adjudication.reviewer_role != "adjudicator":
                raise ValueError("disagreement requires an adjudicator review")
            if adjudication.template_hash != first.template_hash:
                raise ValueError("adjudication must bind the same template")
            if adjudication.reviewer_id in {first.reviewer_id, second.reviewer_id}:
                raise ValueError("adjudicator must be distinct from the two domain reviewers")
        elif adjudication is not None:
            raise ValueError("agreement must not carry unused adjudication")
        expected = sha256_payload(self._payload())
        if self.admission_hash and self.admission_hash != expected:
            raise ValueError("admission_hash mismatch")
        object.__setattr__(self, "admission_hash", expected)

    @property
    def template_hash(self) -> str:
        return self.first_review.template_hash

    @property
    def unresolved(self) -> bool:
        return self.final_disposition == "ambiguous"

    @property
    def final_disposition(self) -> str:
        if self.first_review.disposition == self.second_review.disposition:
            return self.first_review.disposition
        assert self.adjudication is not None
        return self.adjudication.disposition

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "first_review": self.first_review.to_dict(),
            "second_review": self.second_review.to_dict(),
            "adjudication": self.adjudication.to_dict() if self.adjudication else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "final_disposition": self.final_disposition, "admission_hash": self.admission_hash}


@dataclass(frozen=True)
class AdmissionCampaignResultV1:
    reviewed_template_count: int
    admitted_template_count: int
    rejected_template_count: int
    unresolved_template_count: int
    cohen_kappa_basis_points: int
    valid_for_qualification: bool
    failure_reasons: tuple[str, ...]
    campaign_hash: str = ""
    schema_version: str = ADMISSION_CAMPAIGN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ADMISSION_CAMPAIGN_SCHEMA_VERSION:
            raise ValueError("admission campaign schema version mismatch")
        for field_name in (
            "reviewed_template_count",
            "admitted_template_count",
            "rejected_template_count",
            "unresolved_template_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(field_name + " must be a non-negative integer")
        if self.admitted_template_count + self.rejected_template_count + self.unresolved_template_count != self.reviewed_template_count:
            raise ValueError("admission campaign disposition totals do not match reviewed count")
        if not isinstance(self.cohen_kappa_basis_points, int) or not -10_000 <= self.cohen_kappa_basis_points <= 10_000:
            raise ValueError("cohen_kappa_basis_points is invalid")
        reasons = tuple(_identifier(item, "failure_reason") for item in self.failure_reasons)
        object.__setattr__(self, "failure_reasons", reasons)
        expected = sha256_payload(self._payload())
        if self.campaign_hash and self.campaign_hash != expected:
            raise ValueError("campaign_hash mismatch")
        object.__setattr__(self, "campaign_hash", expected)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reviewed_template_count": self.reviewed_template_count,
            "admitted_template_count": self.admitted_template_count,
            "rejected_template_count": self.rejected_template_count,
            "unresolved_template_count": self.unresolved_template_count,
            "cohen_kappa_basis_points": self.cohen_kappa_basis_points,
            "valid_for_qualification": self.valid_for_qualification,
            "failure_reasons": list(self.failure_reasons),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "campaign_hash": self.campaign_hash}


def evaluate_admission_campaign(admissions: Iterable[TaskAdmissionV1]) -> AdmissionCampaignResultV1:
    records = tuple(admissions)
    if not records:
        return AdmissionCampaignResultV1(0, 0, 0, 0, 0, False, ("no_admissions",))
    if not all(isinstance(record, TaskAdmissionV1) for record in records):
        raise ValueError("admissions must be canonical TaskAdmissionV1 records")
    if len({record.template_hash for record in records}) != len(records):
        raise ValueError("admission campaign has duplicate template review")
    pairs = tuple((record.first_review.disposition, record.second_review.disposition) for record in records)
    reasons: list[str] = []
    try:
        kappa = cohen_kappa_basis_points(pairs)
    except ValueError:
        kappa = -10_000
        reasons.append("inter_rater_reliability_unmeasurable")
    admitted = sum(record.final_disposition == "admit" for record in records)
    rejected = sum(record.final_disposition == "reject" for record in records)
    unresolved = sum(record.unresolved for record in records)
    if kappa < 8_000:
        reasons.append("inter_rater_reliability_below_threshold")
    if unresolved * 100 > len(records) * 5:
        reasons.append("unresolved_template_rate_exceeds_five_percent")
    return AdmissionCampaignResultV1(
        reviewed_template_count=len(records),
        admitted_template_count=admitted,
        rejected_template_count=rejected,
        unresolved_template_count=unresolved,
        cohen_kappa_basis_points=kappa,
        valid_for_qualification=not reasons,
        failure_reasons=tuple(reasons),
    )


def cohen_kappa_basis_points(pairs: Iterable[tuple[str, str]]) -> int:
    """Return a fixed-point Cohen's kappa without serializing floats.

    A cohort with only one declared category cannot establish reliability; it
    fails closed instead of treating agreement on an uninformative set as 1.0.
    """
    normalized = tuple((str(left), str(right)) for left, right in pairs)
    if not normalized:
        raise ValueError("kappa requires at least one paired review")
    if any(left not in REVIEW_DISPOSITIONS or right not in REVIEW_DISPOSITIONS for left, right in normalized):
        raise ValueError("kappa review disposition is invalid")
    left_counts = Counter(left for left, _ in normalized)
    right_counts = Counter(right for _, right in normalized)
    if len(set(left_counts) | set(right_counts)) < 2:
        raise ValueError("kappa requires at least two observed dispositions")
    count = len(normalized)
    agreement = sum(left == right for left, right in normalized)
    chance_numerator = sum(left_counts[category] * right_counts[category] for category in REVIEW_DISPOSITIONS)
    numerator = agreement * count - chance_numerator
    denominator = count * count - chance_numerator
    if denominator <= 0:
        raise ValueError("kappa denominator is zero")
    return max(-10_000, min(10_000, numerator * 10_000 // denominator))


__all__ = [
    "AdmissionCampaignResultV1",
    "REVIEW_DISPOSITIONS",
    "TaskAdmissionV1",
    "TaskReviewV1",
    "cohen_kappa_basis_points",
    "evaluate_admission_campaign",
]
