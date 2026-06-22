from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.db.dependencies import get_db_session
from app.db.models import BrokerConnection, User
from app.schemas.broker_connections import (
    BrokerConnectionCreateRequest,
    BrokerConnectionResponse,
    BrokerConnectionUpdateRequest,
)

router = APIRouter(prefix="/broker-connections", tags=["broker-connections"])


def _to_response(item: BrokerConnection) -> BrokerConnectionResponse:
    return BrokerConnectionResponse(
        id=item.id,
        owner_user_id=item.owner_user_id,
        broker_name=item.broker_name,
        account_label=item.account_label,
        environment=item.environment,
        connection_metadata=item.connection_metadata,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=list[BrokerConnectionResponse])
def list_broker_connections(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[BrokerConnectionResponse]:
    rows = db.execute(
        select(BrokerConnection)
        .where(BrokerConnection.owner_user_id == current_user.id)
        .order_by(BrokerConnection.updated_at.desc())
    ).scalars().all()
    return [_to_response(item) for item in rows]


@router.post("", response_model=BrokerConnectionResponse, status_code=status.HTTP_201_CREATED)
def create_broker_connection(
    payload: BrokerConnectionCreateRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> BrokerConnectionResponse:
    connection = BrokerConnection(
        owner_user_id=current_user.id,
        broker_name=payload.broker_name.strip(),
        account_label=payload.account_label.strip(),
        environment=payload.environment.strip(),
        connection_metadata=payload.connection_metadata,
        is_active=payload.is_active,
    )
    db.add(connection)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma ligação com o mesmo broker e etiqueta de conta.",
        ) from None
    db.refresh(connection)
    return _to_response(connection)


@router.put("/{connection_id}", response_model=BrokerConnectionResponse)
def update_broker_connection(
    connection_id: int,
    payload: BrokerConnectionUpdateRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> BrokerConnectionResponse:
    connection = db.execute(
        select(BrokerConnection).where(
            BrokerConnection.id == connection_id,
            BrokerConnection.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ligação não encontrada.")

    if payload.broker_name is not None:
        connection.broker_name = payload.broker_name.strip()
    if payload.account_label is not None:
        connection.account_label = payload.account_label.strip()
    if payload.environment is not None:
        connection.environment = payload.environment.strip()
    if payload.connection_metadata is not None:
        connection.connection_metadata = payload.connection_metadata
    if payload.is_active is not None:
        connection.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma ligação com o mesmo broker e etiqueta de conta.",
        ) from None

    db.refresh(connection)
    return _to_response(connection)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_broker_connection(
    connection_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> None:
    connection = db.execute(
        select(BrokerConnection).where(
            BrokerConnection.id == connection_id,
            BrokerConnection.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ligação não encontrada.")

    db.delete(connection)
    db.commit()
