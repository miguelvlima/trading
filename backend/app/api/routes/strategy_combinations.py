from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.db.dependencies import get_db_session
from app.db.models import StrategyCombination, User
from app.schemas.strategy_combinations import (
    StrategyCombinationCreateRequest,
    StrategyCombinationResponse,
    StrategyCombinationUpdateRequest,
)
from app.services.strategy_engine import get_available_strategies

router = APIRouter(prefix="/strategy-combinations", tags=["strategy-combinations"])


def _validate_strategies(values: list[str]) -> None:
    available = set(get_available_strategies())
    invalid = sorted(set(values) - available)
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown strategies: {', '.join(invalid)}",
        )


def _to_response(item: StrategyCombination, owner_email: str) -> StrategyCombinationResponse:
    return StrategyCombinationResponse(
        id=item.id,
        owner_user_id=item.owner_user_id,
        owner_email=owner_email,
        cloned_from_id=item.cloned_from_id,
        name=item.name,
        description=item.description,
        strategies=item.strategies,
        is_shared=item.is_shared,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=list[StrategyCombinationResponse])
def list_combinations(
    include_private_mine: bool = Query(default=True),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[StrategyCombinationResponse]:
    query = select(StrategyCombination, User.email).join(User, StrategyCombination.owner_user_id == User.id)
    if include_private_mine:
        query = query.where(
            or_(
                StrategyCombination.is_shared.is_(True),
                StrategyCombination.owner_user_id == current_user.id,
            )
        )
    else:
        query = query.where(StrategyCombination.is_shared.is_(True))

    rows = db.execute(query.order_by(StrategyCombination.updated_at.desc())).all()
    return [_to_response(item=row[0], owner_email=row[1]) for row in rows]


@router.post("", response_model=StrategyCombinationResponse, status_code=status.HTTP_201_CREATED)
def create_combination(
    payload: StrategyCombinationCreateRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> StrategyCombinationResponse:
    _validate_strategies(payload.strategies)
    combination = StrategyCombination(
        owner_user_id=current_user.id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        strategies=payload.strategies,
        is_shared=payload.is_shared,
    )
    db.add(combination)
    db.commit()
    db.refresh(combination)
    return _to_response(combination, current_user.email)


@router.post("/{combination_id}/clone", response_model=StrategyCombinationResponse, status_code=status.HTTP_201_CREATED)
def clone_combination(
    combination_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> StrategyCombinationResponse:
    original = db.execute(
        select(StrategyCombination).where(
            StrategyCombination.id == combination_id,
            or_(
                StrategyCombination.is_shared.is_(True),
                StrategyCombination.owner_user_id == current_user.id,
            ),
        )
    ).scalar_one_or_none()
    if original is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Combination not found.")

    clone = StrategyCombination(
        owner_user_id=current_user.id,
        cloned_from_id=original.id,
        name=f"{original.name} (Cópia)",
        description=original.description,
        strategies=original.strategies,
        is_shared=False,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _to_response(clone, current_user.email)


@router.put("/{combination_id}", response_model=StrategyCombinationResponse)
def update_combination(
    combination_id: int,
    payload: StrategyCombinationUpdateRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> StrategyCombinationResponse:
    combination = db.execute(
        select(StrategyCombination).where(
            StrategyCombination.id == combination_id,
            StrategyCombination.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if combination is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Combination not found.")

    if payload.name is not None:
        combination.name = payload.name.strip()
    if payload.description is not None:
        combination.description = payload.description.strip() or None
    if payload.strategies is not None:
        _validate_strategies(payload.strategies)
        combination.strategies = payload.strategies
    if payload.is_shared is not None:
        combination.is_shared = payload.is_shared

    db.commit()
    db.refresh(combination)
    return _to_response(combination, current_user.email)
