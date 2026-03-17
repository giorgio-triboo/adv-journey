def normalize_platform(value: str | None) -> str | None:
    """
    Normalizza il campo piattaforma proveniente dagli export (es. facebook_piattaforma).
    Mappa alias comuni su valori coerenti: 'facebook', 'instagram', 'unknown'.
    """
    if not value:
        return None
    v = value.strip().lower()
    if v in ("fb", "facebook"):
        return "facebook"
    if v in ("ig", "instagram"):
        return "instagram"
    return "unknown"

