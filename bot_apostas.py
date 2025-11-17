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
SEASON_YEAR = datetime.now().year 

# =================================================================
# 2. FUNÇÕES DE CÁLCULO E ESTATÍSTICAS (MÉTODO POISSON)
# =================================================================

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


def calcular_metricas_liga_e_forcas(api_key, league_id, season_year):
    """
    Busca os dados da liga e calcula as Forças de Ataque e Defesa (FA/FD).
    
    ⚠️ ATENÇÃO: Esta função está com DADOS FICTÍCIOS (MOCADOS).
    VOCÊ DEVE SUBSTITUIR O BLOCO ABAIXO PELA LÓGICA DE CHAMADA REAL 
    DA API-FOOTBALL para calcular as médias reais da liga e as forças
    dos times com base nos jogos passados.
    """
    print(f"Buscando métricas para a Liga ID {league_id}...")

    # =================================================================
    # SIMULAÇÃO DE DADOS MOCADOS (SUBSTITUA PELA CHAMADA REAL DA API)
    # =================================================================
    
    # 1. Média de Gols da Liga (MÉTRICAS DA TEMPORADA)
    liga_media_home = 1.55
    liga_media_away = 1.25

    # 2. Força de Ataque (FA) e Defesa (FD) para alguns times (MOCADO)
    team_metrics = {
        # Formato: { 'id_time': [FA_Casa, FD_Casa, FA_Fora, FD_Fora] }
        22: [1.35, 0.85, 1.10, 0.90],  # Exemplo Time Alpha (Alta FA Casa)
        33: [0.90, 1.15, 0.85, 1.05],  # Exemplo Time Beta (Baixa FA Casa)
        40: [1.10, 0.95, 1.25, 0.80],  # Exemplo Time Charlie (Alta FA Fora)
    }
    
    # Adicionando um time para as outras ligas (para não falhar)
    if league_id != 39 and league_id not in team_metrics:
         team_metrics[1] = [1.0, 1.0, 1.0, 1.0] 
         team_metrics[2] = [1.0, 1.0, 1.0, 1.0]

    # =================================================================
    # FIM DA SIMULAÇÃO DE DADOS MOCADOS
    # =================================================================

    return {
        'liga_media_home': liga_media_home,
        'liga_media_away': liga_media_away,
        'team_metrics': team_metrics
    }


def buscar_fixtures_futuros(api_key, league_id):
    """
    Busca jogos futuros na liga especificada (até D+2).
    
    ⚠️ ATENÇÃO: Esta função está com DADOS FICTÍCIOS (MOCADOS).
    VOCÊ DEVE SUBSTITUIR O BLOCO ABAIXO PELA LÓGICA DE CHAMADA REAL 
    DA API-FOOTBALL para buscar os próximos jogos e as odds de mercado.
    """
    data_fim = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
    data_inicio = datetime.now().strftime('%Y-%m-%d')

    print(f"Buscando jogos futuros ({data_inicio} até {data_fim}) para a Liga ID {league_id}...")

    # =================================================================
    # SIMULAÇÃO DE FIXTURES FUTUROS (SUBSTITUA PELA CHAMADA REAL DA API)
    # =================================================================
    fixtures = []
    if league_id == 39: # Premier League
        fixtures = [
            {
                'date': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M'),
                'teams': {'home': {'id': 22, 'name': 'Time Alpha'}, 'away': {'id': 33, 'name': 'Time Beta'}},
                'odds_over_25': 1.95, # ODD MOCADA: BUSQUE ISTO EM UMA API DE ODDS!
                'odds_under_25': 1.90, # ODD MOCADA
            },
            {
                'date': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d %H:%M'),
                'teams': {'home': {'id': 40, 'name': 'Time Charlie'}, 'away': {'id': 22, 'name': 'Time Alpha'}},
                'odds_over_25': 2.15, 
                'odds_under_25': 1.70, 
            }
        ]
    # =================================================================
    # FIM DA SIMULAÇÃO DE FIXTURES
    # =================================================================

    return fixtures


def analisar_jogo(jogo, liga_data):
    """
    Aplica o modelo de Poisson e identifica apostas de Alto Valor/Alta Probabilidade.
    """
    home_id = jogo['teams']['home']['id']
    away_id = jogo['teams']['away']['id']
    home_name = jogo['teams']['home']['name']
    away_name = jogo['teams']['away']['name']
    
    metrics = liga_data['team_metrics']

    if home_id not in metrics or away_id not in metrics:
        return None 

    avg_home = liga_data['liga_media_home']
    avg_away = liga_data['liga_media_away']

    # Forças de Ataque/Defesa
    fa_home = metrics[home_id][0]
    fd_away = metrics[away_id][3]
    fa_away = metrics[away_id][2]
    fd_home = metrics[home_id][1]
    
    # Gols Esperados (EG)
    eg_home = avg_home * fa_home * fd_away
    eg_away = avg_away * fa_away * fd_home
    
    # Probabilidades
    probs = calcular_probabilidade_over_under(eg_home, eg_away)
    
    prob_over_25 = probs['over_25']
    prob_under_25 = probs['under_25']
    
    # Converção de Probabilidade para Odd Justa (Fair Odds)
    try:
        fair_odd_over_25 = 1 / prob_over_25
        fair_odd_under_25 = 1 / prob_under_25
    except ZeroDivisionError:
        return None 

    # Odds do Mercado (MOCADAS)
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
    if (market_odd_over_25 >= (fair_odd_over_25 * VALUE_THRESHOLD) 
        and prob_over_25 >= 0.55):
        apostas_sugeridas.append(
            f"⭐ Alto Valor: Over 2.5 Gols (Odd Mercado: {market_odd_over_25:.2f}, Nossa Odd: {fair_odd_over_25:.2f})"
        )
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
    
    if not API_KEY:
        print("ERRO: API-Football Key não configurada (Variável de Ambiente 'API_FOOTBALL_KEY').")
        return
        
    data_limite = (datetime.now() + timedelta(days=2)).strftime('%d/%m')
    mensagem_final = [f"📊 *ANÁLISES PARA OS PRÓXIMOS 2 DIAS* (Até {data_limite})"]
    total_apostas = 0

    for league_id, league_name in LIGAS_ALVO.items():
        print(f"\nProcessando: {league_name}")

        try:
            liga_data = calcular_metricas_liga_e_forcas(API_KEY, league_id, SEASON_YEAR)
            team_metrics = liga_data.get('team_metrics')
            if not team_metrics:
                print(f"AVISO: Sem métricas de times para {league_name}. Pular.")
                continue
        except Exception as e:
            print(f"ERRO ao buscar métricas da liga {league_name}: {e}")
            continue

        try:
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
                    
                    data_jogo_formatada = datetime.strptime(resultado_analise['data'][:16], '%Y-%m-%d %H:%M').strftime('%d/%m/%Y %H:%M')
                    
                    league_section.append(f"⚽️ *{resultado_analise['jogo']}* ({data_jogo_formatada})")
                    league_section.append(f"EG Casa: {resultado_analise['eg_home']:.2f} | EG Fora: {resultado_analise['eg_away']:.2f}")
                    for sugestao in resultado_analise['sugestoes']:
                        league_section.append(f"  - {sugestao}")
                    league_section.append("") 
            
            if len(league_section) > 1:
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
# 4. EXECUÇÃO E AGENDAMENTO (Adaptado para Render e GitHub Actions)
# =================================================================

def main():
    """
    Configura o agendamento da tarefa e roda o bot.
    """
    print("Bot de Análises de Apostas iniciado.")
    
    # -----------------------------------------------------------------
    # NOVO: Se a variável SINGLE_RUN for 'true', roda uma vez e encerra.
    # Esta variável é injetada pelo GitHub Actions no workflow 'run_bot_manual.yml'
    if os.environ.get("SINGLE_RUN") == "true":
        print("Modo de execução única detectado (GitHub Actions). Rodando análise e encerrando.")
        executar_analise()
        return
    # -----------------------------------------------------------------
        
    # MODO PADRÃO (Ideal para Render: Roda em loop para agendar o horário)
    print("Modo de execução agendada (contínua) detectado (Ideal para Render).")
    
    # Agendar a execução da função de análise todos os dias
    schedule.every().day.at("09:00").do(executar_analise)
    
    # Executa a análise imediatamente ao iniciar (para teste)
    executar_analise() 

    # Loop principal para manter o bot rodando e verificando os agendamentos
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
