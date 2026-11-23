"""HTTP layer. Thin on purpose: all rules live in api/service.py.
Identity comes from three headers (X-User-Id, X-Org-Id, X-Role): a sandbox stand-in for real login."""
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from common.access import AccessDenied, Principal
from common.approval import ApprovalError
from common.sandbox import is_sandbox

from .service import ApiService, Forbidden, NotFound, Unavailable


class ApprovalIn(BaseModel):
    action: str = Field(min_length=1)
    amount_egp: float = Field(ge=0)


class DecisionIn(BaseModel):
    approve: bool
    reason: str | None = None


class QuoteIn(BaseModel):
    buyer_org_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    price_egp: float = Field(gt=0)


class RiskIn(BaseModel):
    cover_days: dict[str, float] = Field(default_factory=dict)   # material -> days of supply
    level: str | None = None
    limit: int | None = None


def get_principal(x_user_id: str | None = Header(None), x_org_id: str | None = Header(None),
                  x_role: str | None = Header(None)) -> Principal:
    if not (x_user_id and x_org_id and x_role):
        raise HTTPException(401, "X-User-Id, X-Org-Id and X-Role headers are required")
    return Principal(x_user_id, x_org_id, x_role)


def call(fn, *args):
    try:
        return fn(*args)
    except Forbidden as e:
        raise HTTPException(403, str(e))
    except (NotFound, AccessDenied) as e:
        raise HTTPException(404, str(e))
    except Unavailable as e:
        raise HTTPException(503, str(e))
    except ApprovalError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


def create_app(service: ApiService | None = None) -> FastAPI:
    svc = service or ApiService(os.environ.get("AUDIT_DB_PATH", "audit.db"),
                                os.environ.get("PLANT_DB_PATH"))
    app = FastAPI(title="Supply Chain Platform API", version="0.2.0")

    @app.get("/health")
    def health():
        return {"status": "ok", "sandbox": is_sandbox()}

    @app.post("/approvals")
    def submit_approval(body: ApprovalIn, who: Principal = Depends(get_principal)):
        return call(svc.submit_approval, who, body.action, body.amount_egp)

    @app.post("/approvals/{request_id}/decision")
    def decide(request_id: str, body: DecisionIn, who: Principal = Depends(get_principal)):
        return call(svc.decide_approval, who, request_id, body.approve, body.reason)

    @app.get("/audit")
    def audit(who: Principal = Depends(get_principal)):
        return call(svc.list_audit, who)

    @app.post("/quotes")
    def submit_quote(body: QuoteIn, who: Principal = Depends(get_principal)):
        return call(svc.submit_quote, who, body.buyer_org_id, body.sku, body.price_egp)

    @app.get("/quotes")
    def list_quotes(who: Principal = Depends(get_principal)):
        return call(svc.list_quotes, who)

    @app.get("/quotes/{quote_id}")
    def get_quote(quote_id: str, who: Principal = Depends(get_principal)):
        return call(svc.get_quote, who, quote_id)

    @app.get("/risk")
    def risk(level: str | None = None, limit: int | None = None, who: Principal = Depends(get_principal)):
        return call(svc.assess_risk, who, None, level, limit)

    @app.post("/risk/assess")
    def risk_with_stock(body: RiskIn, who: Principal = Depends(get_principal)):
        return call(svc.assess_risk, who, body.cover_days, body.level, body.limit)

    return app