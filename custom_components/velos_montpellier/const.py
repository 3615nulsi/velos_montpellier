"""Constantes de l'intégration Vélos Montpellier."""

from datetime import timedelta
from zoneinfo import ZoneInfo

DOMAIN = "velos_montpellier"

# Le premier hôte répond ; le second (annoncé dans la spec OpenAPI) sert de secours.
API_HOSTS = (
    "https://portail-api-data.montpellier.fr",
    "https://portail-api-data.montpellier3m.fr",
)
ENTITY_TYPE = "EcoCounter"
URN_PREFIX = "urn:ngsi-ld:EcoCounter:"

# Les horodatages de l'API portent le suffixe "Z" mais sont en réalité en heure
# de Paris (vérifié : la somme des heures 00h-23h "Z" = total journalier officiel).
DATA_TZ = ZoneInfo("Europe/Paris")

# Totaux journaliers par compteur : `MMM_EcoCompt_<série>.json` (derniers jours) et
# `MMM_EcoCompt_<série>_archive.json` (tout l'historique, plusieurs centaines de ko).
OPEN_DATA_URL = (
    "https://data.montpellier3m.fr/sites/default/files/ressources/"
    "MMM_EcoCompt_{serial}{suffix}.json"
)

CONF_COUNTERS = "counters"
CONF_BACKFILL_DAYS = "backfill_days"

DEFAULT_BACKFILL_DAYS = 365
MAX_BACKFILL_DAYS = 3650

# Les fichiers open data sont mis à jour une fois par jour, le soir (jour J à J+1).
UPDATE_INTERVAL = timedelta(hours=1)
# Jours conservés pour le capteur (le reste est dans les statistiques).
RECENT_DAYS = 7
# Un compteur sans donnée depuis ce délai est considéré inactif (non proposé).
ACTIVE_THRESHOLD = timedelta(days=7)
