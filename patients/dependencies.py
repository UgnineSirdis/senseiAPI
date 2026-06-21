from core.database import SessionDep
from patients.repository import PatientRepository
from patients.service import PatientService


def get_patient_service(session: SessionDep) -> PatientService:
    return PatientService(PatientRepository(session))
