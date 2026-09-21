import re
from typing import Tuple, Optional
from .models import IdentifierFormat


def validate_upes_identifier(identifier: Optional[str]) -> Tuple[bool, str]:
    """
    Validates UPES institutional email contract (FULL_EMAIL format).
    Enforces that the student identifier is an official UPES email:
    e.g. firstname.sapid@stu.upes.ac.in, name@upes.ac.in, name@ddn.upes.ac.in.
    
    Rejects raw numeric SAP IDs (e.g. '500123456') and non-UPES domains.
    """
    if not identifier or not str(identifier).strip():
        return False, "UPES institutional identifier cannot be empty."

    ident = str(identifier).strip().lower()

    # Reject raw numeric SAP IDs
    if re.match(r"^[0-9*]{6,12}$", ident):
        return False, "Numeric SAP ID alone is not supported. Please provide full institutional email (e.g. firstname.sapid@stu.upes.ac.in)."

    if "@" not in ident:
        return False, "Invalid format. Expected institutional email address with '@'."

    # Check institutional domain
    domain = ident.split("@")[-1].strip()
    valid_domains = ("stu.upes.ac.in", "upes.ac.in", "ddn.upes.ac.in", "myupes.ac.in")
    if not any(domain == vd or domain.endswith("." + vd) for vd in valid_domains):
        return False, f"Email domain '{domain}' is not a recognized UPES institutional domain (@stu.upes.ac.in)."

    return True, ""