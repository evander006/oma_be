from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.db.models import (
    Cart,
    CartItem,
    Favorite,
    InstallationService,
    Order,
    OrderItem,
    Product,
    User,
)
from app.db.session import get_db
from app.schemas import (
    CartItemCreate,
    CartOut,
    FavoriteOut,
    InstallationServiceOut,
    OrderCreate,
    OrderOut,
)
from app.services.asset_urls import serialize_product

router = APIRouter(tags=["commerce"])


def _get_or_create_cart(db: Session, user: User) -> Cart:
    cart = db.query(Cart).filter(Cart.user_id == user.id).first()
    if cart:
        return cart
    cart = Cart(user_id=user.id)
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return cart


def _serialize_cart(cart: Cart) -> CartOut:
    items = []
    total = Decimal("0")
    for item in cart.items:
        price = item.product.price or Decimal("0")
        total += price * item.quantity
        items.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "product": serialize_product(item.product),
            }
        )
    return CartOut(id=cart.id, currency=cart.currency, items=items, total=total)


@router.get("/favorites", response_model=list[FavoriteOut])
def list_favorites(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[FavoriteOut]:
    favs = (
        db.query(Favorite)
        .options(joinedload(Favorite.product).joinedload(Product.images))
        .filter(Favorite.user_id == user.id)
        .all()
    )
    return [
        FavoriteOut(id=f.id, product_id=f.product_id, product=serialize_product(f.product))
        for f in favs
    ]


@router.post("/favorites/{product_id}", response_model=FavoriteOut)
def add_favorite(
    product_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> FavoriteOut:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.product_id == product_id)
        .first()
    )
    if not fav:
        fav = Favorite(user_id=user.id, product_id=product_id)
        db.add(fav)
        db.commit()
        db.refresh(fav)
    return FavoriteOut(id=fav.id, product_id=product_id, product=serialize_product(product))


@router.delete("/favorites/{product_id}")
def remove_favorite(
    product_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.product_id == product_id)
        .first()
    )
    if fav:
        db.delete(fav)
        db.commit()
    return {"ok": True}


@router.get("/cart", response_model=CartOut)
def get_cart(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> CartOut:
    cart = _get_or_create_cart(db, user)
    cart = (
        db.query(Cart)
        .options(joinedload(Cart.items).joinedload(CartItem.product).joinedload(Product.images))
        .filter(Cart.id == cart.id)
        .first()
    )
    return _serialize_cart(cart)


@router.post("/cart/items", response_model=CartOut)
def add_cart_item(
    payload: CartItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CartOut:
    if not db.get(Product, payload.product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    cart = _get_or_create_cart(db, user)
    item = (
        db.query(CartItem)
        .filter(CartItem.cart_id == cart.id, CartItem.product_id == payload.product_id)
        .first()
    )
    if item:
        item.quantity += payload.quantity
    else:
        db.add(
            CartItem(cart_id=cart.id, product_id=payload.product_id, quantity=payload.quantity)
        )
    db.commit()
    return get_cart(db, user)


@router.delete("/cart/items/{product_id}", response_model=CartOut)
def remove_cart_item(
    product_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> CartOut:
    cart = _get_or_create_cart(db, user)
    item = (
        db.query(CartItem)
        .filter(CartItem.cart_id == cart.id, CartItem.product_id == product_id)
        .first()
    )
    if item:
        db.delete(item)
        db.commit()
    return get_cart(db, user)


@router.get("/installation-services", response_model=list[InstallationServiceOut])
def installation_services(db: Session = Depends(get_db)) -> list[InstallationService]:
    return db.query(InstallationService).order_by(InstallationService.price.asc()).all()


@router.post("/orders", response_model=OrderOut)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderOut:
    product_ids = list(payload.product_ids)
    quantities: dict[str, int] = {pid: 1 for pid in product_ids}
    if payload.from_cart:
        cart = _get_or_create_cart(db, user)
        for item in cart.items:
            quantities[item.product_id] = item.quantity
            if item.product_id not in product_ids:
                product_ids.append(item.product_id)
    if not product_ids:
        raise HTTPException(status_code=400, detail="No products for order")

    order = Order(
        user_id=user.id,
        installation_service_id=payload.installation_service_id,
        notes=payload.notes,
        is_demonstration=True,
        status="demo_created",
    )
    total = Decimal("0")
    for pid in product_ids:
        product = db.get(Product, pid)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product not found: {pid}")
        qty = quantities.get(pid, 1)
        unit = product.price or Decimal("0")
        total += unit * qty
        order.items.append(
            OrderItem(
                product_id=pid,
                quantity=qty,
                unit_price=product.price,
                currency=product.currency,
            )
        )
    if payload.installation_service_id:
        svc = db.get(InstallationService, payload.installation_service_id)
        if svc:
            total += svc.price
    order.total_amount = total
    db.add(order)
    db.commit()
    db.refresh(order)
    return OrderOut(
        id=order.id,
        status=order.status,
        currency=order.currency,
        total_amount=order.total_amount,
        is_demonstration=order.is_demonstration,
        notes=order.notes,
        items=[
            {
                "id": i.id,
                "product_id": i.product_id,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "currency": i.currency,
            }
            for i in order.items
        ],
    )


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[OrderOut]:
    orders = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.user_id == user.id)
        .order_by(Order.id.desc())
        .all()
    )
    return [
        OrderOut(
            id=o.id,
            status=o.status,
            currency=o.currency,
            total_amount=o.total_amount,
            is_demonstration=o.is_demonstration,
            notes=o.notes,
            items=[
                {
                    "id": i.id,
                    "product_id": i.product_id,
                    "quantity": i.quantity,
                    "unit_price": i.unit_price,
                    "currency": i.currency,
                }
                for i in o.items
            ],
        )
        for o in orders
    ]
