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

CONF_COUNTERS = "counters"
CONF_BACKFILL_DAYS = "backfill_days"

DEFAULT_BACKFILL_DAYS = 30
MAX_BACKFILL_DAYS = 365

UPDATE_INTERVAL = timedelta(minutes=30)
# Fenêtre relue à chaque mise à jour : couvre le retard de publication (8 à 30 h)
# et permet de recalculer le dernier jour complet.
FETCH_WINDOW = timedelta(days=3)
# Taille des tranches de requêtes lors du rattrapage de l'historique.
FETCH_CHUNK = timedelta(days=7)
# Un compteur sans donnée depuis ce délai est considéré inactif (non proposé).
ACTIVE_THRESHOLD = timedelta(days=7)
