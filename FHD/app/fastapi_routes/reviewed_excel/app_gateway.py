"""Application/infrastructure symbols used by reviewed Excel route adapters.

Kept behind one module so adapters and tests patch a single seam.
"""

from __future__ import annotations

from app.application.elt.errors import (
    EltError as EltError,
)
from app.application.elt.errors import (
    ModelAnswerRejected as ModelAnswerRejected,
)
from app.application.elt.errors import (
    ReviewedExcelError as ReviewedExcelError,
)
from app.application.elt.errors import (
    model_call_outcome as model_call_outcome,
)
from app.application.elt.errors import (
    public_excel_error as public_excel_error,
)
from app.application.elt.service_support import (
    dump_json as dump_json,
)
from app.application.elt.service_support import (
    load_json as load_json,
)
from app.application.elt.service_support import (
    new_id as new_id,
)
from app.application.elt.service_support import (
    utcnow as utcnow,
)
from app.application.elt.service_uploads import (
    UploadServiceMixin as UploadServiceMixin,
)
from app.application.elt.service_uploads import (
    discard_stored_upload as discard_stored_upload,
)
from app.application.elt_login_authorization import (
    bind_model_session as bind_model_session,
)
from app.application.elt_login_authorization import (
    model_session_identity as model_session_identity,
)
from app.application.elt_login_authorization import (
    require_model_session as require_model_session,
)
from app.application.elt_login_authorization import (
    template_model_authorization as template_model_authorization,
)
from app.application.reviewed_excel_classification import (
    _classify_semantic_batch as _classify_semantic_batch,
)
from app.application.reviewed_excel_classification import (
    apply_classification_corrections as apply_classification_corrections,
)
from app.application.reviewed_excel_classification import (
    combine_semantic_batches as combine_semantic_batches,
)
from app.application.reviewed_excel_classification import (
    observe_fragment_relationships as observe_fragment_relationships,
)
from app.application.reviewed_excel_classification import (
    plan_semantic_batches as plan_semantic_batches,
)
from app.application.reviewed_excel_classification_store import (
    _CLASS_READY as _CLASS_READY,
)
from app.application.reviewed_excel_classification_store import (
    _classification_cas as _classification_cas,
)
from app.application.reviewed_excel_classification_store import (
    _classification_run as _classification_run,
)
from app.application.reviewed_excel_classification_store import (
    _classification_version as _classification_version,
)
from app.application.reviewed_excel_evidence import (
    bounded_range as bounded_range,
)
from app.application.reviewed_excel_evidence import (
    unresolved_fragments as unresolved_fragments,
)
from app.application.reviewed_excel_review_projection import (
    build_candidate_previews as build_candidate_previews,
)
from app.application.reviewed_excel_review_store import (
    _CLASS_SAVING as _CLASS_SAVING,
)
from app.application.reviewed_excel_review_store import (
    _MODEL_PENDING as _MODEL_PENDING,
)
from app.application.reviewed_excel_review_store import (
    _READY as _READY,
)
from app.application.reviewed_excel_review_store import (
    _SAVED as _SAVED,
)
from app.application.reviewed_excel_review_store import (
    _SAVING as _SAVING,
)
from app.application.reviewed_excel_review_store import (
    _archived_original as _archived_original,
)
from app.application.reviewed_excel_review_store import (
    _cas as _cas,
)
from app.application.reviewed_excel_review_store import (
    _fork_saved_review as _fork_saved_review,
)
from app.application.reviewed_excel_review_store import (
    _intake_selection_key as _intake_selection_key,
)
from app.application.reviewed_excel_review_store import (
    _lock_review_classification as _lock_review_classification,
)
from app.application.reviewed_excel_review_store import (
    _model_processing_failure as _model_processing_failure,
)
from app.application.reviewed_excel_review_store import (
    _proposals as _proposals,
)
from app.application.reviewed_excel_review_store import (
    _rebuild_archived_document as _rebuild_archived_document,
)
from app.application.reviewed_excel_review_store import (
    _refinement_response as _refinement_response,
)
from app.application.reviewed_excel_review_store import (
    _release_failed_review as _release_failed_review,
)
from app.application.reviewed_excel_review_store import (
    _require_private_model as _require_private_model,
)
from app.application.reviewed_excel_review_store import (
    _review_source_version as _review_source_version,
)
from app.application.reviewed_excel_review_store import (
    _run as _run,
)
from app.application.reviewed_excel_review_store import (
    _source as _source,
)
from app.application.reviewed_excel_review_store import (
    _stored_candidate_response as _stored_candidate_response,
)
from app.application.reviewed_excel_review_store import (
    _unlock_review_classification as _unlock_review_classification,
)
from app.application.reviewed_excel_review_store import (
    _update_candidate_claim as _update_candidate_claim,
)
from app.application.reviewed_excel_review_store import (
    _usage_restrictions as _usage_restrictions,
)
from app.application.reviewed_excel_template import (
    MAX_BYTES as MAX_BYTES,
)
from app.application.reviewed_excel_template import (
    classify_review_workbook as classify_review_workbook,
)
from app.application.reviewed_excel_template import (
    clean_workbook as clean_workbook,
)
from app.application.reviewed_excel_template import (
    derive_document_workbook as derive_document_workbook,
)
from app.application.reviewed_excel_template import (
    inspect_workbook as inspect_workbook,
)
from app.application.reviewed_excel_template import (
    make_proposals as make_proposals,
)
from app.application.reviewed_excel_template import (
    refine_proposal as refine_proposal,
)
from app.db.models.elt import (
    EltRun as EltRun,
)
from app.db.models.elt import (
    EltUpload as EltUpload,
)
from app.db.session import (
    get_db as get_db,
)
from app.infrastructure.auth.dependencies import (
    require_permission as require_permission,
)
from app.infrastructure.tenant_scope import (
    tenant_scope as tenant_scope,
)
from app.middleware.error_handler import (
    ReviewedExcelRoute as ReviewedExcelRoute,
)
from app.middleware.error_handler import (
    _reviewed_excel_context as _reviewed_excel_context,
)
from app.utils.operational_errors import (
    BOUNDARY_ERRORS as BOUNDARY_ERRORS,
)
from app.utils.path_io.path_utils import (
    get_app_data_dir as get_app_data_dir,
)

