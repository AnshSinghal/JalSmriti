// JalSmriti access rules, evaluated by Cedar (an AWS open-source policy language) on every write and on
// reads of the review queues and audit log. Reading lakes, places, evidence summaries and dossiers is public.
// Principals are signed-in users (Amazon Cognito). The role comes from the user's Cognito group (citizen when
// none); jurisdictions (area ids, or "*") come from the custom:jurisdictions attribute set for official accounts.
// Every policy has an @id so the app can say exactly which rule allowed or denied a request.

@id("citizens-add-evidence")
permit (principal, action == JalSmriti::Action::"UploadEvidence", resource is JalSmriti::Lake)
when { resource.kind == "lake" };

@id("citizens-create-dossiers")
permit (principal, action == JalSmriti::Action::"CreateDossier", resource is JalSmriti::Lake)
when { resource.kind == "lake" };

@id("anyone-signed-in-watches")
permit (principal, action == JalSmriti::Action::"WatchLake", resource is JalSmriti::Lake);

@id("anyone-signed-in-follows-places")
permit (principal, action == JalSmriti::Action::"FollowPlace", resource is JalSmriti::Area);

@id("citizens-record-rti")
permit (principal, action == JalSmriti::Action::"RecordRti", resource is JalSmriti::Lake)
when { resource.kind == "lake" };

@id("citizens-report-standing-water")
permit (principal, action == JalSmriti::Action::"ReportWaterlogging", resource is JalSmriti::Area);

@id("verifiers-review-water-reports")
permit (principal, action == JalSmriti::Action::"ReviewReport", resource is JalSmriti::Report)
when {
  (principal.role == "verifier" || principal.role == "admin") &&
  (principal.jurisdictions.contains(resource.area) || principal.jurisdictions.contains("*")) &&
  context.hasNote
};

@id("no-self-review-of-water-reports")
forbid (principal, action == JalSmriti::Action::"ReviewReport", resource is JalSmriti::Report)
when { resource.reporter == principal };

@id("creators-mark-submitted")
permit (principal, action == JalSmriti::Action::"MarkSubmitted", resource is JalSmriti::Dossier)
when { resource.creator == principal };

@id("verifiers-review-in-jurisdiction")
permit (principal, action == JalSmriti::Action::"ReviewEvidence", resource is JalSmriti::Evidence)
when {
  (principal.role == "verifier" || principal.role == "admin") &&
  (principal.jurisdictions.contains(resource.area) || principal.jurisdictions.contains("*")) &&
  context.hasNote
};

@id("no-self-verification")
forbid (principal, action == JalSmriti::Action::"ReviewEvidence", resource is JalSmriti::Evidence)
when { resource.uploader == principal };

@id("officers-respond-in-jurisdiction")
permit (principal, action == JalSmriti::Action::"RespondDossier", resource is JalSmriti::Dossier)
when {
  (principal.role == "officer" || principal.role == "admin") &&
  (principal.jurisdictions.contains(resource.area) || principal.jurisdictions.contains("*")) &&
  context.hasNote
};

@id("respond-only-after-submission")
forbid (principal, action == JalSmriti::Action::"RespondDossier", resource is JalSmriti::Dossier)
unless { resource.status == "submitted" || resource.status == "acknowledged" || resource.status == "action_taken" };

@id("officials-see-their-queue")
permit (principal, action == JalSmriti::Action::"ViewQueue", resource is JalSmriti::Area)
when {
  (principal.role == "verifier" || principal.role == "officer" || principal.role == "admin") &&
  (principal.jurisdictions.contains(resource.id) || principal.jurisdictions.contains("*"))
};

@id("officials-see-their-audit-log")
permit (principal, action == JalSmriti::Action::"ViewAudit", resource is JalSmriti::Area)
when {
  (principal.role == "verifier" || principal.role == "officer" || principal.role == "admin") &&
  (principal.jurisdictions.contains(resource.id) || principal.jurisdictions.contains("*"))
};

@id("evidence-is-never-deleted")
forbid (principal, action == JalSmriti::Action::"DeleteEvidence", resource);
