Previsão de Atendimento Presencial – Equatorial (Streamlit)

Dashboard executivo em Python + Streamlit para prever demanda diária, dimensionar equipe, destacar o impacto de feriados e acompanhar satisfação (CSAT) a partir de arquivos CSV.

Entrada de dados na pasta data/

Forecast por arquivo pronto ou por Prophet

Regras de calendário (feriados, pós-feriado) aplicadas de forma transparente

Visualizações claras para apresentação executiva (estilo Power BI)

1) O que é o Streamlit

Streamlit
 é um framework para criar aplicações web de dados usando apenas Python. Excelente para protótipos, relatórios interativos e painéis executivos, sem precisar construir front-end.

2) Estrutura de pastas
seu_projeto/
  app.py
  data/
    feriados_sao_luis_MA_2025.csv               # obrigatório
    satisfacao_origens.csv                      # motivos de procura (opcional, recomendado)
    satisfacao_score.csv                        # CSAT diário (opcional, recomendado)
    senhas_testes_MA_Resumo.csv                 # histórico granular (opcional, recomendado)
    base_MA_Resumo.csv                          # histórico mensal (fallback)
    previsao_atendimento_2025.csv               # previsão pronta (opcional, sobrepõe Prophet)
    1.MA_Resumo_Atendimento_Presencial.xlsx     # fallback para extrair base/senhas
    __tmp_base_from_xlsx.csv                    # temporário (pode ignorar/excluir)


O app usa todos os arquivos acima se estiverem presentes.
Se algum faltar, há fallbacks (detalhes na seção 6).

3) Instalação (Windows)

Crie e ative um ambiente virtual:

python -m venv .venv
.\.venv\Scripts\activate


Instale as dependências:

pip install --upgrade pip
pip install streamlit pandas numpy plotly openpyxl
# Prophet é opcional. Instale se você NÃO tiver 'previsao_atendimento_2025.csv':
pip install prophet cmdstanpy


A primeira execução do Prophet baixa/compila o CmdStan (pode demorar).
Se você já tem previsao_atendimento_2025.csv, o app usa esse arquivo e não precisa do Prophet.

4) Como rodar

Na raiz do projeto (onde fica app.py), com o venv ativo:

python -m streamlit run app.py


Se quiser parar, volte ao terminal e pressione Ctrl+C.

5) Arquivos esperados em data/ (formatos)
5.1 Feriados (obrigatório)

feriados_sao_luis_MA_2025.csv
Colunas: data, nome (o app também aceita ds e holiday).

data,nome
2025-01-01,Confraternização Universal
2025-04-21,Tiradentes
2025-12-25,Natal

5.2 Satisfação – CSAT (opcional, recomendado)

satisfacao_score.csv
Colunas: data, score (0–100).

Origem dos dados: CSV fictício, gerado por IA generativa para demonstração neste projeto.

data,score
2025-12-15,78
2025-12-25,70
2025-12-26,74

5.3 Satisfação – Motivos (opcional, recomendado)

satisfacao_origens.csv
Colunas: origem, contagem.

Também fictício, criado com IA para fins de protótipo.

origem,contagem
Chat do site não resolveu,120
Fila no telefone,95
Aplicativo com erro,70

5.4 Histórico granular (opcional)

senhas_testes_MA_Resumo.csv
O app detecta a coluna data. Se existir volume_atendido, soma por dia; caso contrário, conta linhas.

data,unidade,nome,servicos
2024-05-02,UNIDADE A,MARIA,2ª via
2024-05-02,UNIDADE A,JOÃO,Negociação

5.5 Histórico mensal (fallback)

base_MA_Resumo.csv
Se não houver granular, o app transforma o total mensal em dias úteis (seg–sex, excluindo feriados) do mês.

ano,mes,volume_atendido
2024,5,4200

5.6 Previsão pronta (opcional – sobrepõe Prophet)

previsao_atendimento_2025.csv
Colunas: data (ou ds) e yhat (ou demanda_prevista/y).

data,yhat
2025-12-24,210
2025-12-25,55
2025-12-26,320

5.7 XLSX original (fallback)

1.MA_Resumo_Atendimento_Presencial.xlsx
Se base_MA_Resumo.csv / senhas_testes_MA_Resumo.csv estiverem ausentes ou “brancos”, o app tenta extrair automaticamente as abas mais prováveis.

6) Como o app escolhe as fontes (prioridade)

previsao_atendimento_2025.csv presente?
→ Usa essa previsão e ignora Prophet.

Caso contrário, procura histórico diário em senhas_testes_MA_Resumo.csv e treina Prophet (com feriados).

Se não houver diário, usa base_MA_Resumo.csv (total mensal) e reparte em dias úteis (sem feriados).

Se ainda faltar histórico, cria um histórico sintético apenas para manter a interface funcional (apenas demonstração).

Efeito de calendário (configurável na barra lateral):

Feriado: demanda × 0,25 (reduz 75%)

26/12: demanda × 2,0 (pico pós-Natal)

Dimensionamento da equipe:

atendentes = ceil(demanda_prevista / CAP_POR_ATENDENTE)


Capacidade padrão por atendente: 36 atendimentos/dia (ajuste no código conforme sua operação).

7) Componentes do dashboard

Dia selecionado (KPIs)
Demanda prevista, Atendentes necessários, Status (Feriado / Pós-feriado / Dia útil) e Ocupação da equipe.

Composição da previsão (Waterfall)
Base estatística (modelo) + Efeito de calendário = Previsão final.
Facilita explicar “por que” o número final é aquele.

Satisfação do cliente

Anel CSAT: a fonte é definida no seletor “Fonte da satisfação (CSAT)”:

Auto → usa satisfacao_score.csv se existir; senão, usa estimado (Dia útil 82, Pós-feriado 78, Feriado 72).

Estimado → sempre 82/78/72.

CSV (se existir) → obriga usar o CSV; se não encontrar, cai para estimado com aviso.
Quando há CSV, o app usa o valor do dia mais próximo à data escolhida.

Motivos de procura (barras) a partir de satisfacao_origens.csv.

Próximos 30 dias
Barras (demanda, coloridas por status) + linha (atendentes necessários).

Visão anual
Barras com total mensal + linha de média móvel 7 dias.

Exploratório operacional (se houver senhas_testes_MA_Resumo.csv)
Top unidades, atendentes e serviços observados no histórico.

8) Conversão de XLSX para CSV

Você pode usar Excel/LibreOffice (“Salvar como… CSV”), ou padronizar via Python:

import pandas as pd
df = pd.read_excel("data/1.MA_Resumo_Atendimento_Presencial.xlsx", sheet_name="NomeDaAba")
df.to_csv("data/arquivo_convertido.csv", index=False, encoding="utf-8-sig")


O app já tenta extrair automaticamente do XLSX se os CSVs base/senhas não estiverem disponíveis.

9) Bibliotecas

streamlit – app web interativo

pandas, numpy – manipulação numérica e tabular

plotly – gráficos interativos (barras, linhas, donut, gauge, waterfall)

openpyxl – leitura de Excel (fallback)

prophet (opcional) – previsão temporal com feriados (cmdstanpy é instalado junto)

Instalação resumida:

pip install streamlit pandas numpy plotly openpyxl
# opcional:
pip install prophet cmdstanpy

10) Prompt usado para gerar os CSVs fictícios de satisfação

Estes dados são fictícios e foram gerados por IA generativa exclusivamente para demonstração.

Gere um CSV "satisfacao_score.csv" com colunas:
- data (YYYY-MM-DD) para todo 2025, 1 linha por dia
- score (0-100), valor realista (80–84), caindo para 70 em 25/12 e 74 em 26/12.

Gere também "satisfacao_origens.csv" com:
- origem (texto curto)
- contagem (inteiro)
Inclua motivos como "Chat do site não resolveu", "Fila no telefone", "Aplicativo com erro", etc., com volumes realistas.
Formato CSV com separador vírgula, sem cabeçalhos extras.

11) Passo a passo para replicar na equipe

Copiar este repositório (ou projeto) para a máquina.

Criar e ativar o ambiente virtual; instalar pacotes (seção 3).

Colocar os arquivos na pasta data/ (seção 5).

Rodar: python -m streamlit run app.py.

Na apresentação:

Escolher uma data (ex.: 2025-12-25).

Alternar “Aplicar efeito de feriados”.

Trocar Fonte do CSAT (Auto / Estimado / CSV).

Mostrar a waterfall de composição.

Explorar Próximos 30 dias e Visão anual.

Usar a seção Exploratório se houver senhas.

12) Solução de problemas

“streamlit não é reconhecido” → Rode via python -m streamlit run app.py ou reinstale no venv ativo.

“No module named streamlit” → pip install streamlit no venv ativo.

Prophet lento na 1ª vez → aguardando instalação do CmdStan; para pular, forneça previsao_atendimento_2025.csv.

CSV vazio/corrompido → “No columns to parse from file”; substitua por arquivo válido.

Datas inválidas → verifique formatação YYYY-MM-DD.

Colunas diferentes → os leitores do app fazem “normalização” básica de cabeçalhos; garanta os nomes mínimos listados acima.

13) Observações finais

Este projeto é educacional/prototípico. Ajuste parâmetros, regras de calendário e capacidade por atendente antes de uso operacional.

Os CSVs de satisfação e motivos são sintéticos (IA generativa) e não representam dados reais.

Customizações pedidas (ex.: capacidade por atendente, novas regras de calendário, novos anos de feriados) podem ser adicionadas facilmente no código.
