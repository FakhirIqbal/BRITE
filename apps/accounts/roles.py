"""
Application roles, capability groups and the section registry.

Roles are Workspace groups mapped to application roles; a user may hold
several. Capability groups decide which areas a person can enter; the
defaults per role live in the database (RoleCapabilityDefault) and are
administrator-editable. The section registry drives each role's sidebar.
Sections carry the milestone that ships them; only enabled sections are
served, so a role never sees a section that does not exist yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class Role:
    CEO_EXECUTIVE_ADMIN = "ceo_executive_admin"
    CLINICAL_DIRECTOR = "clinical_director"
    ADMINISTRATOR = "administrator"
    CLIENT_COORDINATOR = "client_coordinator"
    BILLING = "billing"
    HR_STAFFING = "hr_staffing"
    CLINICAL = "clinical"
    OPERATIONS = "operations"
    CREDENTIALING = "credentialing"
    STAFF_SELF_SERVICE = "staff_self_service"

    CHOICES = [
        (CEO_EXECUTIVE_ADMIN, "CEO / Executive Admin"),
        (CLINICAL_DIRECTOR, "Clinical Director"),
        (ADMINISTRATOR, "Administrator"),
        (CLIENT_COORDINATOR, "Client Coordinator"),
        (BILLING, "Billing"),
        (HR_STAFFING, "HR / Staffing"),
        (CLINICAL, "Clinical (BCBA / BCaBA)"),
        (OPERATIONS, "Operations"),
        (CREDENTIALING, "Credentialing"),
        (STAFF_SELF_SERVICE, "Staff (self-service)"),
    ]
    LABELS = dict(CHOICES)
    ORDER = [code for code, _ in CHOICES]


class Capability:
    CLIENT_OPERATIONAL_DATA = "client_operational_data"
    CLIENT_DOCUMENTS_PHI = "client_documents_phi"
    EMPLOYMENT_SCREENING_DETAIL = "employment_screening_detail"
    QUIZ_CONFIGURATION = "quiz_configuration"
    CREDENTIALING = "credentialing"
    AUDIT_HISTORY = "audit_history"
    ADMINISTRATIVE_CONFIGURATION = "administrative_configuration"
    EXPORTS = "exports"

    CHOICES = [
        (CLIENT_OPERATIONAL_DATA, "Client operational data"),
        (CLIENT_DOCUMENTS_PHI, "Client documents / PHI"),
        (EMPLOYMENT_SCREENING_DETAIL, "Employment & screening detail"),
        (QUIZ_CONFIGURATION, "Quiz configuration"),
        (CREDENTIALING, "Credentialing"),
        (AUDIT_HISTORY, "Audit history"),
        (ADMINISTRATIVE_CONFIGURATION, "Administrative configuration"),
        (EXPORTS, "Exports"),
    ]
    LABELS = dict(CHOICES)
    ORDER = [code for code, _ in CHOICES]


class Level:
    NONE = "none"
    VIEW = "view"
    EDIT = "edit"
    CHOICES = [(NONE, "None"), (VIEW, "View"), (EDIT, "Edit")]
    LABELS = dict(CHOICES)
    RANK = {NONE: 0, VIEW: 1, EDIT: 2}

    @classmethod
    def highest(cls, *levels: str) -> str:
        best = cls.NONE
        for level in levels:
            if cls.RANK.get(level, 0) > cls.RANK[best]:
                best = level
        return best

    @classmethod
    def satisfies(cls, held: str, required: str) -> bool:
        return cls.RANK.get(held, 0) >= cls.RANK.get(required, 0)


# Proposed defaults (design "Default access by role · capability groups"),
# seeded into RoleCapabilityDefault and editable by administrators.
DEFAULT_ROLE_CAPABILITIES: dict[str, dict[str, str]] = {
    Role.CEO_EXECUTIVE_ADMIN: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.VIEW,
        Capability.CLIENT_DOCUMENTS_PHI: Level.VIEW,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.VIEW,
        Capability.QUIZ_CONFIGURATION: Level.NONE,
        Capability.CREDENTIALING: Level.VIEW,
        Capability.AUDIT_HISTORY: Level.VIEW,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.NONE,
        Capability.EXPORTS: Level.VIEW,
    },
    Role.CLINICAL_DIRECTOR: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.EDIT,
        Capability.CLIENT_DOCUMENTS_PHI: Level.VIEW,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.VIEW,
        Capability.QUIZ_CONFIGURATION: Level.NONE,
        Capability.CREDENTIALING: Level.NONE,
        Capability.AUDIT_HISTORY: Level.VIEW,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.NONE,
        Capability.EXPORTS: Level.NONE,
    },
    Role.ADMINISTRATOR: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.NONE,
        Capability.CLIENT_DOCUMENTS_PHI: Level.NONE,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.NONE,
        Capability.QUIZ_CONFIGURATION: Level.EDIT,
        Capability.CREDENTIALING: Level.NONE,
        Capability.AUDIT_HISTORY: Level.VIEW,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.EDIT,
        Capability.EXPORTS: Level.EDIT,
    },
    Role.CLIENT_COORDINATOR: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.EDIT,
        Capability.CLIENT_DOCUMENTS_PHI: Level.EDIT,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.NONE,
        Capability.QUIZ_CONFIGURATION: Level.NONE,
        Capability.CREDENTIALING: Level.NONE,
        Capability.AUDIT_HISTORY: Level.NONE,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.NONE,
        Capability.EXPORTS: Level.NONE,
    },
    Role.BILLING: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.EDIT,
        Capability.CLIENT_DOCUMENTS_PHI: Level.VIEW,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.NONE,
        Capability.QUIZ_CONFIGURATION: Level.NONE,
        Capability.CREDENTIALING: Level.VIEW,
        Capability.AUDIT_HISTORY: Level.NONE,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.NONE,
        Capability.EXPORTS: Level.NONE,
    },
    Role.HR_STAFFING: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.VIEW,
        Capability.CLIENT_DOCUMENTS_PHI: Level.NONE,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.EDIT,
        Capability.QUIZ_CONFIGURATION: Level.NONE,
        Capability.CREDENTIALING: Level.VIEW,
        Capability.AUDIT_HISTORY: Level.NONE,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.NONE,
        Capability.EXPORTS: Level.NONE,
    },
    Role.CLINICAL: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.VIEW,
        Capability.CLIENT_DOCUMENTS_PHI: Level.VIEW,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.NONE,
        Capability.QUIZ_CONFIGURATION: Level.NONE,
        Capability.CREDENTIALING: Level.NONE,
        Capability.AUDIT_HISTORY: Level.NONE,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.NONE,
        Capability.EXPORTS: Level.NONE,
    },
    Role.OPERATIONS: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.VIEW,
        Capability.CLIENT_DOCUMENTS_PHI: Level.NONE,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.NONE,
        Capability.QUIZ_CONFIGURATION: Level.NONE,
        Capability.CREDENTIALING: Level.NONE,
        Capability.AUDIT_HISTORY: Level.VIEW,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.NONE,
        Capability.EXPORTS: Level.NONE,
    },
    Role.CREDENTIALING: {
        Capability.CLIENT_OPERATIONAL_DATA: Level.NONE,
        Capability.CLIENT_DOCUMENTS_PHI: Level.NONE,
        Capability.EMPLOYMENT_SCREENING_DETAIL: Level.VIEW,
        Capability.QUIZ_CONFIGURATION: Level.NONE,
        Capability.CREDENTIALING: Level.EDIT,
        Capability.AUDIT_HISTORY: Level.NONE,
        Capability.ADMINISTRATIVE_CONFIGURATION: Level.NONE,
        Capability.EXPORTS: Level.NONE,
    },
    Role.STAFF_SELF_SERVICE: {cap: Level.NONE for cap in Capability.ORDER},
}

# Workspace group -> role mapping proposed in the design; seeded, editable.
DEFAULT_GROUP_MAPPINGS: list[tuple[str, str]] = [
    ("executive", Role.CEO_EXECUTIVE_ADMIN),
    ("clinical-director", Role.CLINICAL_DIRECTOR),
    ("app-admins", Role.ADMINISTRATOR),
    ("intake-coordinators", Role.CLIENT_COORDINATOR),
    ("billing", Role.BILLING),
    ("hr-staffing", Role.HR_STAFFING),
    ("clinical-bcba", Role.CLINICAL),
    ("operations", Role.OPERATIONS),
    ("credentialing", Role.CREDENTIALING),
    ("all-staff", Role.STAFF_SELF_SERVICE),
]


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    path: str
    icon: str
    milestone: int
    enabled: bool = False
    # Optional capability requirement beyond holding the role.
    capability: str | None = None
    level: str = Level.VIEW
    badge: str | None = None


@dataclass(frozen=True)
class SectionGroup:
    label: str
    sections: tuple[Section, ...] = field(default_factory=tuple)


# Section registry by role. `enabled` is flipped as milestones deliver the page.
SECTION_REGISTRY: dict[str, tuple[SectionGroup, ...]] = {
    Role.CLIENT_COORDINATOR: (
        SectionGroup(
            "Work",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("quick_inquiry", "Quick Inquiry", "/quick-inquiry", "plus", 3),
                Section("referral_pipeline", "Referral Pipeline", "/referral-pipeline", "layers", 3),
                Section("follow_up_aging", "Follow-up & Aging", "/follow-up", "clock", 3),
                Section("clients", "Clients", "/clients", "users", 2, True, Capability.CLIENT_OPERATIONAL_DATA),
                Section("documents_questionnaires", "Documents & Questionnaires", "/documents", "file-text", 3),
                Section("cancellation_log", "Cancellation Log", "/cancellation-log", "list", 8),
            ),
        ),
    ),
    Role.BILLING: (
        SectionGroup(
            "Work",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("benefits_verification", "Benefits Verification", "/benefits", "shield-check", 4),
                Section("funding_pathways", "Funding Pathways", "/funding", "dollar-sign", 4),
                Section("authorizations", "Authorizations", "/authorizations", "clipboard", 4),
                Section("payer_knowledge", "Payer Knowledge", "/payer-knowledge", "message-square", 4),
                Section("service_start", "Service Start Confirmation", "/service-start", "play", 7),
                Section("clients", "Clients", "/clients", "users", 2, True, Capability.CLIENT_OPERATIONAL_DATA),
            ),
        ),
    ),
    Role.HR_STAFFING: (
        SectionGroup(
            "Staffing",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("staffing_search", "Staffing Search", "/staffing", "heart-handshake", 6),
                Section("school_readiness", "School Readiness", "/school-readiness", "school", 6),
                Section("cancellation_log", "Cancellation Log", "/cancellation-log", "list", 8),
                Section("clients", "Clients", "/clients", "users", 2, True, Capability.CLIENT_OPERATIONAL_DATA),
            ),
        ),
        SectionGroup(
            "People (restricted)",
            (
                Section("needs_review", "Needs Review", "/needs-review", "inbox", 5, False, Capability.EMPLOYMENT_SCREENING_DETAIL),
                Section("candidates", "Candidates / Talent Pool", "/candidates", "users", 5, False, Capability.EMPLOYMENT_SCREENING_DETAIL),
                Section("staff", "Staff", "/staff", "user", 5, False, Capability.EMPLOYMENT_SCREENING_DETAIL),
                Section("training", "Training & Remediation", "/training", "graduation-cap", 5, False, Capability.EMPLOYMENT_SCREENING_DETAIL),
                Section("badges", "Badges", "/badges", "id-card", 5, False, Capability.EMPLOYMENT_SCREENING_DETAIL),
            ),
        ),
    ),
    Role.CLINICAL: (
        SectionGroup(
            "My work",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("my_clients", "My Assigned Clients", "/my-clients", "users", 6),
                Section("assessments", "Assessments", "/assessments", "calendar", 6),
                Section("plans", "Plans & Revisions", "/plans", "file-text", 6),
                Section("integrity_gate", "Integrity Gate", "/integrity-gate", "shield-check", 6),
                Section("preservice_reviews", "RBT Pre-service Reviews", "/preservice-reviews", "check", 7),
            ),
        ),
    ),
    Role.CLINICAL_DIRECTOR: (
        SectionGroup(
            "Review",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("assignment_approvals", "Assignment Approvals", "/assignment-approvals", "check", 6),
                Section("plan_reviews", "Plan Reviews", "/plan-reviews", "file-text", 6),
                Section("integrity_clearance", "Integrity Clearance", "/integrity-clearance", "shield-check", 6),
                Section("partial_denied", "Partial / Denied Auths", "/partial-denied", "clipboard", 4),
                Section("readiness_review", "Readiness Review", "/readiness-review", "target", 7),
            ),
        ),
        SectionGroup(
            "Visibility",
            (
                Section("clients", "Clients", "/clients", "users", 2, True, Capability.CLIENT_OPERATIONAL_DATA),
                Section("operations_overview", "Operations Overview", "/operations", "grid", 8),
                Section("cancellation_log", "Cancellation Log", "/cancellation-log", "list", 8),
            ),
        ),
    ),
    Role.OPERATIONS: (
        SectionGroup(
            "Oversight",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("operations_overview", "Operations Overview", "/operations", "grid", 8),
                Section("unassigned", "Unassigned", "/unassigned", "inbox", 8),
                Section("queues", "Queues", "/queues", "list", 8),
                Section("stabilization", "Stabilization Reviews", "/stabilization", "clock", 7),
                Section("cancellation_log", "Cancellation Log", "/cancellation-log", "list", 8),
                Section("clients", "Clients", "/clients", "users", 2, True, Capability.CLIENT_OPERATIONAL_DATA),
            ),
        ),
    ),
    Role.ADMINISTRATOR: (
        SectionGroup(
            "Administration",
            (
                Section("admin_home", "Home", "/admin", "home", 2, True, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("configuration", "Configuration", "/admin/configuration", "settings", 2, True, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("users_access", "Users & Access", "/admin/users", "users", 2, True, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("temporary_grants", "Temporary Grants", "/admin/temporary-grants", "clock", 2, True, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("system_owners", "System Owners", "/admin/system-owners", "shield-check", 2, True, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("workspace_groups", "Workspace Groups", "/admin/workspace-groups", "key", 2, True, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("shared_drive", "Shared Drive", "/admin/shared-drive", "folder", 2, True, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("restricted_allowlist", "Restricted Allowlist", "/admin/restricted-allowlist", "lock", 5, False, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("document_sensitivity", "Document Sensitivity", "/admin/document-sensitivity", "layers", 5, False, Capability.ADMINISTRATIVE_CONFIGURATION),
                Section("audit_history", "Audit History", "/admin/audit", "history", 2, True, Capability.AUDIT_HISTORY),
                Section("exports", "Exports", "/admin/exports", "download", 8, False, Capability.EXPORTS),
                Section("migration", "Migration & Cutover", "/admin/migration", "database", 9, False, Capability.ADMINISTRATIVE_CONFIGURATION),
            ),
        ),
    ),
    Role.CEO_EXECUTIVE_ADMIN: (
        SectionGroup(
            "CEO / Executive Admin",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("operations_overview", "Operations Overview", "/operations", "grid", 8),
                Section("staff_documents", "Staff Documents", "/staff-documents", "file-text", 5, False, Capability.EMPLOYMENT_SCREENING_DETAIL),
                Section("clients", "Clients", "/clients", "users", 2, True, Capability.CLIENT_OPERATIONAL_DATA),
                Section("audit_history", "Audit History", "/admin/audit", "history", 2, True, Capability.AUDIT_HISTORY),
            ),
        ),
    ),
    Role.CREDENTIALING: (
        SectionGroup(
            "Credentialing",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("work_queue", "Work Queue", "/credentialing/queue", "list", 8),
                Section("enrollments", "Enrollments", "/credentialing/enrollments", "building", 5),
                Section("needs_association", "Needs Association", "/credentialing/needs-association", "inbox", 8),
                Section("knowledge_base", "Knowledge Base", "/credentialing/knowledge", "book", 8),
                Section("guided_checklists", "Guided Checklists", "/credentialing/checklists", "check-square", 8),
                Section("screening_records", "Screening Records", "/credentialing/screening", "search", 5),
                Section("expirations", "Expirations & Cycles", "/credentialing/expirations", "refresh", 8),
                Section("legacy_reconciliation", "Legacy Reconciliation", "/credentialing/legacy", "file", 8),
            ),
        ),
    ),
    Role.STAFF_SELF_SERVICE: (
        SectionGroup(
            "My account",
            (
                Section("home", "Home", "/", "home", 2, True),
                Section("my_training", "My Training", "/me/training", "graduation-cap", 5),
                Section("my_readiness", "My Readiness", "/me/readiness", "check", 5),
                Section("my_badge", "My Badge", "/me/badge", "id-card", 5),
            ),
        ),
    ),
}

# Sections a user may reach through an individual exception even without the role.
EXCEPTION_SECTIONS: dict[str, Section] = {
    Capability.AUDIT_HISTORY: Section("audit_history", "Audit History", "/admin/audit", "history", 2, True, Capability.AUDIT_HISTORY),
    Capability.CLIENT_OPERATIONAL_DATA: Section("clients", "Clients", "/clients", "users", 2, True, Capability.CLIENT_OPERATIONAL_DATA),
    Capability.ADMINISTRATIVE_CONFIGURATION: Section("admin_home", "Administration", "/admin", "settings", 2, True, Capability.ADMINISTRATIVE_CONFIGURATION),
}


def role_label(code: str) -> str:
    return Role.LABELS.get(code, code)
