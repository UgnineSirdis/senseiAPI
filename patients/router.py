import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from patients.dependencies import get_patient_service
from patients.models import PatientNotFoundError
from patients.schemas import PatientCreate, PatientOut, PatientUpdate
from patients.service import PatientService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def add_patient(
    payload: PatientCreate,
    service: PatientService = Depends(get_patient_service),
) -> PatientOut:
    try:
        patient = await service.add_patient(
            name=payload.name,
            phone=payload.phone,
            email=payload.email,
        )
    except SQLAlchemyError as exc:
        logger.error("failed to create patient", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to create patient",
        ) from exc
    return PatientOut.from_patient(patient)


@router.get("", response_model=list[PatientOut])
async def list_patients(
    service: PatientService = Depends(get_patient_service),
) -> list[PatientOut]:
    try:
        patients = await service.list_patients()
    except SQLAlchemyError as exc:
        logger.error("failed to list patients", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to list patients",
        ) from exc
    return [PatientOut.from_patient(patient) for patient in patients]


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    service: PatientService = Depends(get_patient_service),
) -> PatientOut:
    try:
        patient = await service.update_patient(
            patient_id,
            payload.model_dump(exclude_unset=True),
        )
    except PatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        logger.error("failed to update patient", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to update patient",
        ) from exc
    return PatientOut.from_patient(patient)


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient(
    patient_id: uuid.UUID,
    service: PatientService = Depends(get_patient_service),
) -> None:
    try:
        await service.delete_patient(patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        logger.error("failed to delete patient", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to delete patient",
        ) from exc
