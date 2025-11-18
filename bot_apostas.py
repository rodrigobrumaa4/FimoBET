import requests
import json
from datetime import datetime

API_KEY = "9eee578f035bf7ecf4baa20a316782a1"  # <<< COLOQUE SUA KEY AQUI
BASE_URL = "https://v3.football.api-sports.io/fixtures"


def get_finished_matches(league_id, season, statuses="FT-AET-PEN"):
    """
    Busca jogos finalizados na API-Football.
    """
    headers = {
        "x-apisports-key": API_KEY
    }

    params = {
        "league": league_id,
        "season": season,
        "status": statuses  # FT = tempo normal, AET = prorrogação, PEN = pênaltis
    }

    print(f"\n🔍 Buscando jogos da liga {league_id} - temporada {season}...")

    response = requests.get(BASE_URL, headers=headers, params=params)

    # Log da resposta bruta (para debugging)
    print("Status Code:", response.status_code)

    try:
        data = response.json()
        print("Resposta da API:", json.dumps(data, indent=4, ensure_ascii=False))
    except:
        print("Erro ao decodificar JSON")
        return []

    # Valida estrutura
    if "response" not in data:
        print("❌ Resposta malformada!")
        return []

    matches = data["response"]

    print(f"✅ Jogos encontrados: {len(matches)}")
    return matches


# ------------------------------------------
# EXEMPLO DE USO
# ------------------------------------------

if __name__ == "__main__":
    # IDs de ligas comuns na API-Football
    leagues = {
        "Premier League": 39,
        "La Liga": 140,
        "Bundesliga": 78,
        "Serie A": 135,
        "Brasileirão Série A": 71
    }

    season = 2024  # Temporada mais comum

    for league_name, league_id in leagues.items():
        print(f"\n==============================")
        print(f"🏆 {league_name}")
        print("==============================")

        matches = get_finished_matches(league_id, season)

        # Exemplo: imprime os primeiros 3 jogos
        for match in matches[:3]:
            home = match["teams"]["home"]["name"]
            away = match["teams"]["away"]["name"]
            goals_home = match["goals"]["home"]
            goals_away = match["goals"]["away"]

            print(f"→ {home} {goals_home} x {goals_away} {away}")
