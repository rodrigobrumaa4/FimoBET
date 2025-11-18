# -*- coding: utf-8 -*-
import requests
import json
import pandas as pd
from scipy.stats import poisson
import schedule
import time
from datetime import datetime, timedelta
import os
import sys

# =================================================================
# 1. CONFIGURAÇÕES - LENDO DE VARIÁVEIS DE AMBIENTE (SECRETS DO GITHUB)
# =================================================================
# O código irá procurar essas variáveis nos "GitHub Secrets" ou no seu servidor
API_KEY = os.environ.get("API_FOOTBALL_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Configurações globais da API-Football
API_BASE_URL = "https://v3.football.api-sports.io/"
API_HEADERS = {
    'x-apisports-key': API_KEY
}

# Ligas com Maior Liquidez (IDs da API-Football)
# Você pode consultar os IDs na documentação da API
LIGAS_ALVO = {
    39: "Premier League (Inglaterra)",
    140: "La Liga (Espanha)",
    78: "Bundesliga (Alemanha)",
    135: "Serie A (Itália)",
    71: "Brasileirão Série A (Brasil)"
}
# Temporada atual que você deseja analisar
# IMPORTANTE PARA TESTE: Mantendo 2024, pois os dados dessa temporada
# já estão 100% disponíveis na API, o que ajuda a isolar problemas de chave/limite.
SEASON_YEAR = 2024 

# =================================================================
# 2. FUNÇÕES DE CÁLCULO E ESTATÍSTICAS (MÉTODO POISSON)
# =================================================================

def _chamar_api(endpoint, params):
    """Função auxiliar para fazer chamadas à API e tratar erros."""
    if not API_KEY:
        print("ERRO: API_FOOTBALL_KEY não configurada.")
        return None
        
    url = API_BASE_URL + endpoint
    
    # Atualiza o cabeçalho caso a API_KEY tenha sido carregada depois
    API_HEADERS['x-apisports-key'] = API_KEY 
    
    try:
        response = requests.get(url, headers=API_HEADERS, params=params, timeout=15)
        response.raise_for_status() # Lança um erro para códigos de status 4xx/5xx
        data = response.json()
        
        # A API-Football retorna os dados em 'response'
        if data and data.get('response'):
            return data['response']
        else:
            print(f"AVISO: Nenhuma resposta válida da API para {endpoint} com params {params}.")
            # Note: Este aviso é comum se o limite de requisições foi atingido ou a chave está inativa.
            return None
            
    except requests.exceptions.HTTPError as e:
        print(f"ERRO HTTP ao chamar {endpoint}: {e}")
        print(f"Resposta de erro: {e.response.text}")
    except requests.exceptions.RequestException as e:
        print(f"ERRO de conexão/timeout ao chamar {endpoint}: {e}")
    except Exception as e:
        print(f"ERRO inesperado ao processar a resposta da API: {e}")
        
    return None


def calcular_probabilidade_poisson(expected_goals, goals_to_check):
    """
    Calcula a probabilidade exata de um número de gols usando a
    Distribuição de Poisson.
    """
    # Usamos scipy para cálculos de Poisson de alta precisão
    return poisson.pmf(goals_to_check, expected_goals)

def calcular_probabilidade_over_under(eg_home, eg_away):
    """
    Calcula as probabilidades de Over/Under 2.5 e Ambas Marcam (BTTS).
    """
    prob_total_goals = {}
    
    # Simula todos os placares possíveis (ex: até 5x5) para calcular o total
    for home_goals in range(6): 
        for away_goals in range(6):
            # Probabilidade do placar exato
            prob_placar = (calcular_probabilidade_poisson(eg_home, home_goals) * calcular_probabilidade_poisson(eg_away, away_goals))
            
            total_goals = home_goals + away_goals
            # O get() garante que a soma acumule a probabilidade
            prob_total_goals[total_goals] = prob_total_goals.get(total_goals, 0) + prob_placar 

    # Probabilidade Over 2.5: Soma das probabilidades de placares com 3+ gols
    prob_over_25 = sum(prob_total_goals.get(gols, 0) for gols in range(3, 11))

    # Probabilidade BTTS (Ambas Marcam): Probabilidade de Home > 0 E Away > 0
    prob_btts = (1 - calcular_probabilidade_poisson(eg_home, 0)) * (1 - calcular_probabilidade_poisson(eg_away, 0))
    
    return {
        'over_25': prob_over_25,
        'under_25': 1 - prob_over_25,
        'btts_sim': prob_btts
    }


def _processar_fixtures_para_metricas(fixtures):
    """
    Calcula as métricas da liga (médias) e as forças dos times (FA/FD)
    com base nos fixtures finalizados.
    """
    
    # Dicionários para acumular dados
    team_stats = {}
    total_goals_home = 0
    total_goals_away = 0
    total_games = len(fixtures)
    
    if total_games == 0:
        print("ERRO: Nenhuma partida finalizada encontrada para a temporada. Impossível calcular FA/FD.")
        return None, None, None

    # --- 1. Passagem: Coletar Gols Totais da Liga e Estatísticas Brutas dos Times ---
    for item in fixtures:
        fixture = item.get('fixture', {})
        teams = item.get('teams', {})
        score = item.get('score', {}).get('fulltime', {})
        
        # Garante que temos todos os dados necessários
        if not all([teams, score, teams['home']['id'], teams['away']['id']]):
            continue

        home_id = teams['home']['id']
        away_id = teams['away']['id']
        goals_home = score.get('home')
        goals_away = score.get('away')
        
        if goals_home is None or goals_away is None:
            continue
            
        goals_home = int(goals_home)
        goals_away = int(goals_away)
        
        total_goals_home += goals_home
        total_goals_away += goals_away

        # Inicializa o time se não existir
        for team_id in [home_id, away_id]:
            if team_id not in team_stats:
                team_stats[team_id] = {
                    'name': teams['home']['name'] if team_id == home_id else teams['away']['name'],
                    'gph': 0, 'gpa': 0, # Jogos Jogados Home/Away
                    'gsh': 0, 'gch': 0, # Gols Marcados/Sofridos Home
                    'gsa': 0, 'gca': 0  # Gols Marcados/Sofridos Away
                }
        
        # Estatísticas do Time da Casa
        stats_home = team_stats[home_id]
        stats_home['gph'] += 1
        stats_home['gsh'] += goals_home
        stats_home['gch'] += goals_away
        
        # Estatísticas do Time Visitante
        stats_away = team_stats[away_id]
        stats_away['gpa'] += 1
        stats_away['gsa'] += goals_away
        stats_away['gca'] += goals_home


    # --- 2. Cálculo das Médias da Liga ---
    liga_media_home = total_goals_home / total_games
    liga_media_away = total_goals_away / total_games
    
    print(f"Média de Gols da Liga (Casa): {liga_media_home:.2f} | (Fora): {liga_media_away:.2f}")

    # --- 3. Cálculo das Forças de Ataque e Defesa (FA/FD) por Time ---
    team_metrics = {}
    
    # Fórmulas de Poisson:
    # FA_H = (Gols Marcados Casa do Time / Jogos Casa do Time) / Média Gols Casa da Liga
    # FD_H = (Gols Sofridos Casa do Time / Jogos Casa do Time) / Média Gols Fora da Liga (pois o adversário marcou a média do Away)
    
    for team_id, stats in team_stats.items():
        # Evita divisão por zero se o time não jogou em casa ou fora
        avg_gsh = stats['gsh'] / stats['gph'] if stats['gph'] > 0 else 0
        avg_gch = stats['gch'] / stats['gph'] if stats['gph'] > 0 else 0
        avg_gsa = stats['gsa'] / stats['gpa'] if stats['gpa'] > 0 else 0
        avg_gca = stats['gca'] / stats['gpa'] if stats['gpa'] > 0 else 0
        
        # Cálculos de FA/FD (Fator de Correção: 1.0 se a média da liga for zero)
        
        # Casa
        fa_home = avg_gsh / liga_media_home if liga_media_home > 0 else 1.0
        fd_home = avg_gch / liga_media_away if liga_media_away > 0 else 1.0 # Baseado na média AWAY
        
        # Fora
        fa_away = avg_gsa / liga_media_away if liga_media_away > 0 else 1.0
        fd_away = avg_gca / liga_media_home if liga_media_home > 0 else 1.0 # Baseado na média HOME

        # Formato: [FA_Casa, FD_Casa, FA_Fora, FD_Fora]
        team_metrics[team_id] = [fa_home, fd_home, fa_away, fd_away]
        
    return liga_media_home, liga_media_away, team_metrics


def calcular_metricas_liga_e_forcas(api_key, league_id, season_year):
    """
    Busca os dados da API-Football e calcula as Forças de Ataque e Defesa (FA/FD).
    """
    print(f"Buscando histórico de jogos (FT) para a Liga ID {league_id} na temporada {season_year}...")

    params = {
        'league': league_id,
        'season': season_year,
        'status': 'FT' # Apenas jogos Finalizados (Full Time)
        # Atenção: a API-Football usa paginação. Para ligas grandes, pode ser necessário um loop para buscar todas as páginas.
        # Estamos assumindo que os resultados de uma temporada cabem em uma única página para simplificar o código.
    }
    
    api_response = _chamar_api("fixtures", params)
    
    if not api_response:
        return {
            'liga_media_home': 1.5, 
            'liga_media_away': 1.2, 
            'team_metrics': {} # Retorna vazio se não houver dados
        }

    # Processa os dados da API para obter as métricas reais
    liga_media_home, liga_media_away, team_metrics = _processar_fixtures_para_metricas(api_response)
    
    if not team_metrics:
        # Retorna médias padrões e métricas vazias se o cálculo falhar (ex: total_games=0)
        return {
            'liga_media_home': 1.5, 
            'liga_media_away': 1.2, 
            'team_metrics': {} 
        }

    return {
        'liga_media_home': liga_media_home,
        'liga_media_away': liga_media_away,
        'team_metrics': team_metrics
    }


def buscar_fixtures_futuros(api_key, league_id):
    """
    Busca jogos futuros na liga especificada (até D+15) usando a API-Football.
    """
    
    # Define o intervalo de datas: Hoje até D+15 (incluído)
    data_hoje = datetime.now().strftime('%Y-%m-%d')
    data_limite = (datetime.now() + timedelta(days=15)).strftime('%Y-%m-%d')
    
    # Parâmetros para buscar fixtures futuros
    params = {
        'league': league_id,
        'season': SEASON_YEAR,
        'from': data_hoje,
        'to': data_limite
        # IMPORTANTE: As odds (probabilidades de mercado) não vêm neste endpoint. 
        # Buscar odds requer um endpoint separado (/odds) e uma chamada para cada jogo. 
        # Continuaremos MOCANDO as odds para evitar milhares de chamadas à API.
    }
    
    print(f"Buscando jogos futuros ({data_hoje} até {data_limite}) para a Liga ID {league_id}...")
    
    api_response = _chamar_api("fixtures", params)
    
    fixtures_reais = []
    
    if api_response:
        # Extrai os dados relevantes dos fixtures
        for item in api_response:
            fixture = item.get('fixture', {})
            teams = item.get('teams', {})
            
            # Buscando odds MOCADAS
            odds_over_25 = 1.95 
            odds_under_25 = 1.90
            
            fixtures_reais.append({
                'date': fixture.get('date'),
                'teams': {
                    'home': {'id': teams['home']['id'], 'name': teams['home']['name']},
                    'away': {'id': teams['away']['id'], 'name': teams['away']['name']},
                },
                # ODDS MOCADAS AINDA: Para evitar 100+ chamadas à API para cada odd
                'odds_over_25': odds_over_25, 
                'odds_under_25': odds_under_25, 
            })
            
    if not fixtures_reais:
        print(f"AVISO: A API-Football não retornou jogos futuros para a Liga ID {league_id}. Verifique a SEASON_YEAR.")
        
    return fixtures_reais


def analisar_jogo(jogo, liga_data):
    """
    Aplica o modelo de Poisson e identifica apostas de Alto Valor/Alta Probabilidade.
    """
    home_id = jogo['teams']['home']['id']
    away_id = jogo['teams']['away']['id']
    home_name = jogo['teams']['home']['name']
    away_name = jogo['teams']['away']['name']
    
    metrics = liga_data['team_metrics']

    # Garante que as métricas (FA/FD) foram calculadas
    if home_id not in metrics or away_id not in metrics:
        print(f"AVISO: Métricas FA/FD não calculadas ou insuficientes para {home_name} ({home_id}) vs {away_name} ({away_id}). Pulando.")
        return None 

    avg_home = liga_data['liga_media_home']
    avg_away = liga_data['liga_media_away']

    # Forças de Ataque/Defesa (Usando as métricas REAIS)
    fa_home = metrics[home_id][0]
    fd_away = metrics[away_id][3]
    fa_away = metrics[away_id][2]
    fd_home = metrics[home_id][1]
    
    # Gols Esperados (EG)
    # EG Home = Média Gols Casa da Liga * FA_Home * FD_Away
    eg_home = avg_home * fa_home * fd_away
    # EG Away = Média Gols Fora da Liga * FA_Away * FD_Home
    eg_away = avg_away * fa_away * fd_home
    
    # Probabilidades
    probs = calcular_probabilidade_over_under(eg_home, eg_away)
    
    prob_over_25 = probs['over_25']
    prob_under_25 = probs['under_25']
    
    # Converção de Probabilidade para Odd Justa (Fair Odds)
    try:
        # Probabilidade mínima de 0.01 para evitar ZeroDivisionError e odds infinitas
        prob_over_25_safe = max(prob_over_25, 0.01)
        prob_under_25_safe = max(prob_under_25, 0.01)

        fair_odd_over_25 = 1 / prob_over_25_safe
        fair_odd_under_25 = 1 / prob_under_25_safe
    except ZeroDivisionError:
        return None 

    # Odds do Mercado (Ainda MOCADAS)
    market_odd_over_25 = jogo.get('odds_over_25', 1.0)
    market_odd_under_25 = jogo.get('odds_under_25', 1.0)
    
    apostas_sugeridas = []
    
    # A) ALTA PROBABILIDADE (Aposta Segura - > 75% de chance)
    if prob_over_25 >= 0.75:
        apostas_sugeridas.append(
            f"🎯 Alta Probabilidade: Over 2.5 Gols (Prob: {prob_over_25:.2%})"
        )
    elif prob_under_25 >= 0.75:
        apostas_sugeridas.append(
            f"🎯 Alta Probabilidade: Under 2.5 Gols (Prob: {prob_under_25:.2%})"
        )
        
    # B) ALTO VALOR (Value Bet - Mercado paga mais que nossa Odd Justa)
    VALUE_THRESHOLD = 1.10 # Mercado paga 10% a mais que nossa odd justa
    
    # Condição: Odd de Mercado é 'Value' E a Probabilidade mínima é razoável (55%)
    # Over 2.5
    if (market_odd_over_25 >= (fair_odd_over_25 * VALUE_THRESHOLD) 
        and prob_over_25 >= 0.55):
        apostas_sugeridas.append(
            f"⭐ Alto Valor: Over 2.5 Gols (Odd Mercado: {market_odd_over_25:.2f}, Nossa Odd: {fair_odd_over_25:.2f})"
        )
    # Under 2.5
    if (market_odd_under_25 >= (fair_odd_under_25 * VALUE_THRESHOLD) 
        and prob_under_25 >= 0.55):
        apostas_sugeridas.append(
            f"⭐ Alto Valor: Under 2.5 Gols (Odd Mercado: {market_odd_under_25:.2f}, Nossa Odd: {fair_odd_under_25:.2f})"
        )

    if apostas_sugeridas:
        return {
            'jogo': f"{home_name} vs {away_name}",
            'data': jogo['date'],
            'eg_home': eg_home,
            'eg_away': eg_away,
            'sugestoes': apostas_sugeridas
        }
    return None

# =================================================================
# 3. FUNÇÃO DE EXECUÇÃO E TELEGRAM
# =================================================================

def enviar_mensagem_telegram(mensagem):
    """
    Envia a mensagem formatada para o grupo/canal do Telegram.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERRO: Token ou Chat ID do Telegram não configurados (Variáveis de Ambiente).")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': mensagem,
        'parse_mode': 'Markdown'
    }
    
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status() 
        print("Mensagem enviada com sucesso para o Telegram.")
    except requests.exceptions.RequestException as e:
        print(f"ERRO ao enviar para o Telegram: {e}")


def executar_analise():
    """
    Função principal que busca dados, calcula e envia as análises.
    """
    print(f"\n--- INICIANDO ANÁLISE DE JOGOS {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    # Verifica se a chave da API está disponível no início
    if not API_KEY:
        print("ERRO: API-Football Key não configurada (Variável de Ambiente 'API_FOOTBALL_KEY').")
        return
        
    # A data limite agora é D+15, e o texto da mensagem foi atualizado
    data_limite = (datetime.now() + timedelta(days=15)).strftime('%d/%m')
    mensagem_final = [f"📊 *ANÁLISES PARA OS PRÓXIMOS 15 DIAS* (Até {data_limite})"]
    total_apostas = 0

    for league_id, league_name in LIGAS_ALVO.items():
        print(f"\nProcessando: {league_name} (ID: {league_id})")

        try:
            # AGORA CHAMA A FUNÇÃO QUE BUSCA OS DADOS REAIS DE JOGOS FINALIZADOS E CALCULA AS MÉTRICAS
            liga_data = calcular_metricas_liga_e_forcas(API_KEY, league_id, SEASON_YEAR)
            team_metrics = liga_data.get('team_metrics')
            
            if not team_metrics:
                print(f"AVISO: Sem métricas de times calculadas (jogos insuficientes ou erro da API) para {league_name}. Pular.")
                continue
                
        except Exception as e:
            print(f"ERRO CRÍTICO ao buscar e calcular métricas da liga {league_name}: {e}")
            continue

        try:
            # Busca os fixtures futuros (agora com janela de 15 dias)
            fixtures = buscar_fixtures_futuros(API_KEY, league_id)
        except Exception as e:
            print(f"ERRO ao buscar fixtures de {league_name}: {e}")
            continue

        if fixtures:
            league_section = [f"\n--- 🏆 {league_name} ---"]
            
            for jogo in fixtures:
                resultado_analise = analisar_jogo(jogo, liga_data)
                
                if resultado_analise:
                    total_apostas += 1
                    
                    # A data da API vem em 'YYYY-MM-DDTHH:MM:SS+00:00'. Ajuste o formato.
                    try:
                        data_jogo_formatada = datetime.fromisoformat(resultado_analise['data'].replace('Z', '+00:00')).strftime('%d/%m/%Y %H:%M')
                    except ValueError:
                         # Tenta parsear formatos mais simples se o fromisoformat falhar
                        data_jogo_formatada = resultado_analise['data']
                        
                    
                    league_section.append(f"⚽️ *{resultado_analise['jogo']}* ({data_jogo_formatada})")
                    league_section.append(f"EG Casa: {resultado_analise['eg_home']:.2f} | EG Fora: {resultado_analise['eg_away']:.2f}")
                    for sugestao in resultado_analise['sugestoes']:
                        league_section.append(f"  - {sugestao}")
                    league_section.append("") 
            
            # Adiciona a seção da liga apenas se houver análises nela
            if len(league_section) > 2: # Mais do que o título e a quebra de linha
                mensagem_final.extend(league_section)

    if total_apostas > 0:
        mensagem_final.append(f"\n✅ *{total_apostas} análises de valor encontradas!*")
        mensagem_final.append("Lembre-se: Aposte com responsabilidade.")
        
        mensagem_a_enviar = "\n".join(mensagem_final)
        enviar_mensagem_telegram(mensagem_a_enviar)
    else:
        mensagem_final.append("\n⚠️ *Nenhuma aposta de Alto Valor/Probabilidade Alta encontrada nesta rodada.*")
        print("Nenhuma aposta encontrada. Nenhuma mensagem enviada.")


# =================================================================
# 4. EXECUÇÃO E AGENDAMENTO
# =================================================================

def main():
    """
    Configura o agendamento da tarefa e roda o bot.
    """
    print("Bot de Análises de Apostas iniciado.")
    
    # -----------------------------------------------------------------
    # MODO DE EXECUÇÃO ÚNICA (GitHub Actions)
    if os.environ.get("SINGLE_RUN") == "true":
        print("Modo de execução única detectado (GitHub Actions). Rodando análise e encerrando.")
        executar_analise()
        return
    # -----------------------------------------------------------------
        
    # MODO PADRÃO (Ideal para Render: Roda em loop para agendar o horário)
    print("Modo de execução agendada (contínua) detectado.")
    
    # Agendar a execução da função de análise todos os dias
    schedule.every().day.at("09:00").do(executar_analise)
    
    # Executa a análise imediatamente ao iniciar
    executar_analise() 

    # Loop principal para manter o bot rodando e verificando os agendamentos
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
