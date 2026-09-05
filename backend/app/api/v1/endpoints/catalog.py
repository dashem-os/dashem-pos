import uuid
import re
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import PLATFORM_MANAGERS
from app.core.access import require_platform_role
from app.core.context import TenantContext, get_tenant_context
from app.core.config import settings
from app.core.database import get_session
from app.core.security import AuthPrincipal, get_current_principal
from app.models.catalog import (
    Category, Combo, ItemTypeEnum, Modifier, ModifierGroup, Product,
    PlatformMediaAsset, ProductModifierGroup, ProductPrice, QuickAccessProduct,
)
from app.models.assortment import SalesContextEnum
from app.api.v1.endpoints import assortments
from app.services import catalog_service, media_service, starter_catalog_service
from app.services.supabase_storage import (
    PLATFORM_LIBRARY_BUCKET, SupabaseStorageClient, SupabaseStorageRejected,
    SupabaseStorageUnavailable, validate_content_signature, validate_filename_content_type,
)

router = APIRouter()
router.include_router(assortments.router, prefix="/assortments", tags=["Assortments & Menus"])


class CategoryCreateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    parent_id: Optional[uuid.UUID] = None


class CategoryUpdateDTO(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    slug: Optional[str] = Field(default=None, min_length=2, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    parent_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


class ProductCreateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    sku: str = Field(min_length=1, max_length=100)
    barcode: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = None
    image_url: Optional[str] = Field(default=None, max_length=500)
    unit: str = Field(default="UN", min_length=1, max_length=16)
    category_id: Optional[uuid.UUID] = None
    item_type: ItemTypeEnum = ItemTypeEnum.PRODUCT
    tracks_inventory: Optional[bool] = None
    requires_fulfillment: Optional[bool] = None
    available_for_sale: bool = True
    allows_multi_flavor: bool = False
    production_destination: Optional[str] = Field(default=None, max_length=80)


class ProductUpdateDTO(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    sku: Optional[str] = Field(default=None, min_length=1, max_length=100)
    barcode: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = None
    image_url: Optional[str] = Field(default=None, max_length=500)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=16)
    category_id: Optional[uuid.UUID] = None
    item_type: Optional[ItemTypeEnum] = None
    tracks_inventory: Optional[bool] = None
    requires_fulfillment: Optional[bool] = None
    is_active: Optional[bool] = None
    available_for_sale: Optional[bool] = None
    allows_multi_flavor: Optional[bool] = None
    production_destination: Optional[str] = Field(default=None, max_length=80)


class ProductPriceCreateDTO(BaseModel):
    product_id: uuid.UUID
    cost_price: Decimal = Field(ge=0)
    sale_price: Decimal = Field(ge=0)
    store_id: Optional[uuid.UUID] = None


class SellableProductDTO(BaseModel):
    id: uuid.UUID
    name: str
    sku: str
    barcode: Optional[str]
    description: Optional[str]
    image_url: Optional[str]
    unit: str
    item_type: ItemTypeEnum
    category_id: Optional[uuid.UUID]
    category_name: Optional[str]
    tracks_inventory: bool
    requires_fulfillment: bool
    available_for_sale: bool
    allows_multi_flavor: bool
    production_destination: Optional[str]
    sale_price: Decimal
    cost_price: Decimal
    margin_percent: Decimal
    quantity: Decimal
    minimum_stock: Decimal
    is_low_stock: bool
    quick_position: Optional[int]


class SellableProductPageDTO(BaseModel):
    items: List[SellableProductDTO]
    total: int
    page: int
    page_size: int


class QuickAccessDTO(BaseModel):
    position: int = Field(ge=1, le=99)


class LayoutScopeDTO(BaseModel):
    """The arrangement belongs to a context and an activity, never to "the store".

    Someone who works the counter and the takeaway had ambiguous positions while
    the arrangement ignored both.
    """

    sales_context: Optional[str] = None
    business_activity: Optional[str] = None


class StoreLayoutReorderDTO(LayoutScopeDTO):
    product_ids: List[uuid.UUID]
    # 0 means "this window does not exist yet". Sending the version the caller
    # was looking at is what makes two managers reordering it a 409 instead of a
    # silent overwrite.
    expected_version: int = Field(ge=0)


class QuickAccessReorderDTO(LayoutScopeDTO):
    product_ids: List[uuid.UUID]


class ModifierGroupCreateDTO(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    minimum_choices: int = Field(default=0, ge=0)
    maximum_choices: int = Field(default=1, ge=1)
    is_required: bool = False


class ModifierCreateDTO(BaseModel):
    group_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    price_delta: Decimal = Decimal("0")


class ProductModifierGroupDTO(BaseModel):
    group_id: uuid.UUID
    position: int = Field(default=1, ge=1)


class ComboItemDTO(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(default=Decimal("1"), gt=0)


class ComboCreateDTO(BaseModel):
    product_id: uuid.UUID
    name: str = Field(min_length=2, max_length=160)
    items: List[ComboItemDTO] = Field(min_length=1)


@router.post("/categories", response_model=Category)
def create_category_endpoint(data: CategoryCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_category(session, context, data.name, data.slug, data.parent_id)


@router.get("/categories", response_model=List[Category])
def list_categories_endpoint(include_inactive: bool = False, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.list_categories(session, context, include_inactive)


@router.patch("/categories/{category_id}", response_model=Category)
def update_category_endpoint(category_id: uuid.UUID, data: CategoryUpdateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.update_category(session, context, category_id, data.model_dump(exclude_unset=True))


@router.delete("/categories/{category_id}", response_model=Category)
def archive_category_endpoint(category_id: uuid.UUID, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.archive_category(session, context, category_id)


@router.post("/products", response_model=Product)
def create_product_endpoint(data: ProductCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_product(session, context, **data.model_dump())


@router.get("/products", response_model=List[Product])
def list_products_endpoint(category_id: Optional[uuid.UUID] = None, search: Optional[str] = None, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.list_products(session, context, category_id, search)


@router.patch("/products/{product_id}", response_model=Product)
def update_product_endpoint(product_id: uuid.UUID, data: ProductUpdateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.update_product(session, context, product_id, data.model_dump(exclude_unset=True))


@router.delete("/products/{product_id}", response_model=Product)
def archive_product_endpoint(product_id: uuid.UUID, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.archive_product(session, context, product_id)


@router.get("/sellable-products", response_model=SellableProductPageDTO)
def sellable_products_endpoint(
    sales_context: Optional[SalesContextEnum] = Query(default=None, description="Contexto de venda obrigatório exceto em modo master"),
    channel_id: Optional[uuid.UUID] = Query(default=None, description="Canal de venda opcional"),
    master: bool = Query(default=False, description="Visualizar catálogo mestre da unidade"),
    activity: Optional[str] = Query(default=None, max_length=40, description="Atividade de negócio ativa (FOOD_SERVICE, RETAIL, BEAUTY_RESELLER)"),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=160), category_id: Optional[uuid.UUID] = None,
    quick_access: bool = False, context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    return catalog_service.list_sellable_products(
        session, context, page, page_size, search, category_id, quick_access,
        sales_context=sales_context, channel_id=channel_id, master=master, activity=activity,
    )


class StarterCatalogueDTO(BaseModel):
    activity: str = Field(min_length=1, max_length=40)
    actor_id: Optional[uuid.UUID] = None


@router.post("/starter-catalogue")
def publish_starter_catalogue_endpoint(
    data: StarterCatalogueDTO,
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    """Management publishes a set for one contracted activity; the POS consumes it."""
    if "catalog.update" not in context.permissions and context.auth_subject != "local-auth-bypass":
        raise HTTPException(status_code=403, detail="Publicar catálogo inicial exige autorização de catálogo.")
    return starter_catalog_service.publish_starter_catalogue(
        session, context, data.activity, data.actor_id
    )


@router.post("/prices", response_model=ProductPrice)
def upsert_product_price_endpoint(data: ProductPriceCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_product_price(session, context, data.product_id, float(data.cost_price), float(data.sale_price), data.store_id)


@router.get("/prices", response_model=List[ProductPrice])
def list_product_prices_endpoint(store_id: Optional[uuid.UUID] = None, product_id: Optional[uuid.UUID] = None, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.list_prices(session, context, store_id, product_id)


class ProductMediaDTO(BaseModel):
    """Either a file the shopkeeper uploaded, or a picture from the shelf."""

    bucket_id: Optional[str] = None
    object_path: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: int = 0
    original_filename: Optional[str] = None
    library_asset_id: Optional[uuid.UUID] = None


@router.get("/media-library")
def search_media_library_endpoint(search: Optional[str] = None, activity: Optional[str] = None, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.search_media_library(session, search, activity)


@router.get("/platform/media-library")
def list_platform_media_library_endpoint(
    search: Optional[str] = None,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return catalog_service.search_media_library(session, search=search, limit=100)


@router.post("/platform/media-library", status_code=201)
async def upload_platform_media_library_endpoint(
    request: Request,
    code: str = Query(min_length=2, max_length=80),
    name: str = Query(min_length=2, max_length=160),
    filename: str = Query(min_length=3, max_length=160),
    collection: str = Query(default="GENERIC", max_length=80),
    tags: str = Query(default="", max_length=500),
    activities: str = Query(default="", max_length=300),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """Owner-only ingress for the shared shelf; it never touches media_assets."""

    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    normalized_code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]+", normalized_code):
        raise HTTPException(status_code=422, detail="Código da imagem inválido.")
    if session.exec(select(PlatformMediaAsset.id).where(PlatformMediaAsset.code == normalized_code)).first():
        raise HTTPException(status_code=409, detail="Já existe uma imagem com este código na biblioteca DASHEM.")

    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="A biblioteca aceita JPEG, PNG ou WebP.")
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.strip()).strip("-.")[-100:]
    object_path = f"catalog/{uuid.uuid4()}-{safe_filename}"
    try:
        validate_filename_content_type(object_path, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > settings.STORAGE_MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Imagem excede o limite individual permitido.")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    try:
        validate_content_signature(content, content_type)
        storage = SupabaseStorageClient()
        storage.ensure_platform_library_bucket()
        stored = storage.upload_library(object_path, content, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SupabaseStorageRejected as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SupabaseStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    asset = PlatformMediaAsset(
        code=normalized_code,
        name=name.strip(),
        bucket_id=PLATFORM_LIBRARY_BUCKET,
        object_path=stored.object_path,
        content_type=content_type,
        suggested_activities=[item.strip().upper() for item in activities.split(",") if item.strip()],
        tags=[item.strip().lower() for item in tags.split(",") if item.strip()],
        collection=collection.strip().upper() or "GENERIC",
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    signed = media_service.sign_library_asset(asset)
    return {
        "id": str(asset.id), "code": asset.code, "name": asset.name,
        "collection": asset.collection, "tags": asset.tags,
        "suggested_activities": asset.suggested_activities,
        "url": signed[0] if signed else None,
    }


@router.put("/products/{product_id}/media", response_model=Product)
def set_product_media_endpoint(product_id: uuid.UUID, data: ProductMediaDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.set_product_media(
        session, context, product_id,
        bucket_id=data.bucket_id, object_path=data.object_path, content_type=data.content_type,
        size_bytes=data.size_bytes, original_filename=data.original_filename,
        library_asset_id=data.library_asset_id,
    )


@router.get("/layout")
def get_store_layout_endpoint(sales_context: Optional[str] = None, business_activity: Optional[str] = None, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.get_store_layout(session, context, sales_context, business_activity)


@router.put("/layout")
def reorder_store_layout_endpoint(data: StoreLayoutReorderDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.reorder_store_layout(
        session, context, data.product_ids, data.expected_version,
        data.sales_context, data.business_activity,
    )


@router.get("/quick-access", response_model=List[QuickAccessProduct])
def list_quick_access_endpoint(sales_context: Optional[str] = None, business_activity: Optional[str] = None, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.list_quick_access(session, context, sales_context, business_activity)


@router.put("/quick-access", response_model=List[QuickAccessProduct])
def reorder_quick_access_endpoint(data: QuickAccessReorderDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.reorder_quick_access(
        session, context, data.product_ids, data.sales_context, data.business_activity,
    )


@router.put("/quick-access/{product_id}", response_model=QuickAccessProduct)
def set_quick_access_endpoint(product_id: uuid.UUID, data: QuickAccessDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.set_quick_access(session, context, product_id, data.position)


@router.delete("/quick-access/{product_id}", status_code=204)
def remove_quick_access_endpoint(product_id: uuid.UUID, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    catalog_service.remove_quick_access(session, context, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/modifier-groups", response_model=ModifierGroup, status_code=201)
def create_modifier_group_endpoint(data: ModifierGroupCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_modifier_group(session, context, data.name, data.minimum_choices, data.maximum_choices, data.is_required)


@router.post("/modifiers", response_model=Modifier, status_code=201)
def create_modifier_endpoint(data: ModifierCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_modifier(session, context, data.group_id, data.name, float(data.price_delta))


@router.post("/products/{product_id}/modifier-groups", response_model=ProductModifierGroup, status_code=201)
def link_modifier_group_endpoint(product_id: uuid.UUID, data: ProductModifierGroupDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.link_modifier_group(session, context, product_id, data.group_id, data.position)


@router.post("/combos", response_model=Combo, status_code=201)
def create_combo_endpoint(data: ComboCreateDTO, context: TenantContext = Depends(get_tenant_context), session: Session = Depends(get_session)):
    return catalog_service.create_combo(session, context, data.product_id, data.name, [(item.product_id, item.quantity) for item in data.items])
