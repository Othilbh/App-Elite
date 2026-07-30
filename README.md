# Elite Hapkido — Check-in de Treinos

App para os alunos registrarem presença nos treinos, com ranking semanal/mensal/anual e prêmio de fim de ano. Funciona no navegador do celular — não precisa instalar nada (e pode ser "instalado" como PWA, ver abaixo).

## Como funciona

- **Aluno**: na home, digita seu nome (ou apelido) e o PIN de 4 números, e clica em "Entrar" — como um login normal, sem precisar tocar em fotos. Dentro do painel dele, toca em "Registrar treino de hoje". O check-in fica pendente.
- **Professor**: entra em "Sou o professor" (senha padrão `treino123`), vê os check-ins pendentes e confirma ou rejeita cada um. Só check-ins confirmados contam no ranking.
- **Ranking**: página pública com abas Semana / Mês / Ano, mostrando todos os alunos ordenados por treinos confirmados. O professor logado vê um link para **exportar o ranking em Excel (.xlsx)**.
- **Prêmio anual**: no painel do professor, em "Campeões", o botão "Fechar ano" registra o aluno com mais treinos confirmados no ano como campeão, criando um histórico (Hall da Fama) para os próximos anos.

### Visual: faixas e pódio

- Cada aluno tem uma **faixa** (branca → amarela → verde → azul → vermelha → preta) que sobe conforme o total de treinos confirmados ao longo do tempo, com barra de progresso até a próxima — visível no painel do próprio aluno.
- O "Top 3 do ano" na home aparece em formato de **pódio** (1º mais alto e destacado com coroa, 2º e 3º nas laterais), em vez de três cartões iguais.
- Alunos sem foto cadastrada ganham um avatar colorido (cor fixa por aluno), para facilitar reconhecer o cartão de cada um nas listas.

### PIN individual do aluno (com bloqueio de segurança)

Cada aluno tem um PIN de 4 números, para que só ele consiga fazer check-in em seu próprio nome.

- Ao cadastrar um aluno, você pode digitar um PIN específico ou deixar em branco para o sistema gerar um automaticamente.
- O PIN de cada aluno aparece na lista em **Painel → Alunos** — é aí que você pega o número para repassar a ele.
- Se o aluno esquecer o PIN, use o botão **"Gerar novo PIN"** na mesma tela.
- **Bloqueio automático**: depois de 5 tentativas erradas seguidas, o acesso daquele aluno fica bloqueado por 15 minutos (evita que alguém fique tentando adivinhar o PIN de outra pessoa). O professor pode liberar na hora gerando um novo PIN.
- **O aluno pode trocar seu próprio PIN**: dentro do painel dele, em "🔒 Alterar meu PIN". A partir do momento em que ele troca, o professor deixa de ver o número em texto claro na lista de alunos (aparece "alterado pelo aluno") — vira realmente uma senha pessoal, não uma senha que o professor definiu e conhece. Se o aluno esquecer o PIN próprio, o professor ainda consegue destravar gerando um novo (que volta a ficar visível pra ele, até o aluno trocar de novo).
- Alunos cadastrados antes dessa funcionalidade existir continuam entrando sem PIN normalmente (não trava ninguém de fora).

### Fotos comprimidas automaticamente

Toda foto enviada no cadastro é redimensionada (no máximo 720px no lado maior) e salva como JPEG otimizado — reduz bastante o espaço ocupado, sem perda visível de qualidade num avatar de app.

### Módulo financeiro: Mensalidades

Nova área **"Mensalidades"** no menu do professor, com gestão completa de pagamentos:

- **Dashboard** com indicadores (alunos ativos, receita prevista/recebida do mês, valor pendente, inadimplentes, % de inadimplência) e três gráficos (receita por mês, formas de pagamento, evolução da inadimplência) — feitos com Chart.js, carregado via CDN, sem precisar instalar nada no servidor.
- **Geração automática**: um botão gera a mensalidade do mês seguinte para todos os alunos com `billing_status = ativo` e valor de mensalidade configurado. Não duplica quem já tem a mensalidade daquele mês gerada.
- **Atraso automático**: toda vez que a tela de Mensalidades é aberta, mensalidades pendentes com vencimento já passado viram "Atrasado" sozinhas — não precisa de um robô/cron rodando em segundo plano, porque essa checagem roda no próprio carregamento da página.
- **Ações por mensalidade**: registrar pagamento (com forma de pagamento), marcar como isenta, editar (valor, vencimento, status, data/forma de pagamento, observações) ou excluir.
- **Filtros**: por nome do aluno, modalidade, status, mês, ano e forma de pagamento.
- **Perfil financeiro do aluno** (`💰 Financeiro` na lista de Alunos): dados cadastrais, histórico completo de mensalidades, estatísticas de treino (check-ins na semana/mês/ano, total de treinos, posição no ranking do ano, última presença) e a situação financeira atual, tudo na mesma tela.
- **Indicador visual na lista de Alunos**: 🟢 em dia / 🟡 vence hoje / 🔴 em atraso, baseado na mensalidade mais recente de cada aluno.
- Os dados financeiros (valor da mensalidade, dia de vencimento, modalidade, status de matrícula, observações) ficam na "Ficha completa" de cada aluno, junto dos outros dados cadastrais.

Esse módulo é totalmente separado do sistema de faixa por frequência (o indicador de progresso do check-in) — um é sobre dinheiro, o outro é sobre engajamento nos treinos.

### Ficha completa do aluno

Além do cadastro rápido (nome, apelido, PIN), o professor pode abrir a **"Ficha completa"** de cada aluno (na tela Alunos) para registrar:

- Foto
- Data de nascimento (a idade é calculada automaticamente)
- **Faixa oficial** — a graduação real do aluno no Hapkido, definida pelo professor. É diferente do indicador de "faixa" que aparece no painel do aluno, que é apenas um contador de frequência/engajamento, não uma graduação de verdade. As duas aparecem separadas e identificadas para não gerar confusão.
- Telefone do aluno
- Nome e telefone do responsável (para os menores de idade)
- Endereço
- **Aluno ativo** — desmarque se ele saiu da academia ou está afastado por um tempo. Ele some do ranking e da tela de check-in, mas todo o histórico de treinos continua salvo (dá pra reativar quando ele voltar). O cadastro rápido continua criando o aluno já como ativo; esse é só um jeito a mais e mais visível de desativar, além do botão "Remover" que já existia na lista.

Esses dados são visíveis só na área do professor — não aparecem em nenhuma tela pública nem no painel do próprio aluno (exceto a faixa oficial, que é mostrada a ele).

## Banco de dados: SQLite (local) ou Postgres (produção)

O app detecta sozinho qual banco usar:

- **Sem a variável de ambiente `DATABASE_URL`**: usa SQLite local (`checkin.db`), ótimo para testar na sua máquina.
- **Com `DATABASE_URL` definida**: usa Postgres — é isso que você deve configurar em produção, para o histórico e as fotos não serem apagados a cada deploy.

### Onde conseguir um Postgres gratuito

Duas opções simples:

1. **Supabase** (recomendado se você já usa Supabase em outros projetos seus): crie um novo projeto (ou uma tabela separada num projeto existente), vá em **Project Settings → Database → Connection string** (modo "URI"), copie a string e cole como `DATABASE_URL` no Render.
2. **Render Postgres**: no painel do Render, **New → PostgreSQL**. Ele te dá uma "Internal Database URL" — copie e cole como variável `DATABASE_URL` no seu Web Service. **Atenção**: no plano gratuito do Render, o banco Postgres expira depois de um tempo (histórico costumava ser ~30 dias) e é apagado — para uso contínuo, ou paga o plano do banco, ou usa o Supabase, que tem um free tier mais duradouro. Vale conferir os termos atuais direto no site do Render/Supabase antes de decidir, pois esse tipo de política muda com frequência.

Depois de configurar `DATABASE_URL` e reiniciar o serviço, o app cria as tabelas sozinho no Postgres na primeira execução (mesma lógica do `init_db()` que já existia para o SQLite).

## Rodar localmente (para testar)

Requer Python 3.9+.

```bash
pip install -r requirements.txt
python app.py
```

Abra `http://localhost:5000` no navegador. Para outros aparelhos na mesma rede Wi-Fi acessarem, use o IP do seu computador, por exemplo `http://192.168.0.10:5000`.

Antes de usar de verdade, troque a senha do professor: defina a variável de ambiente `ADMIN_PASSWORD` (ou edite a constante `ADMIN_PASSWORD` no topo de `app.py`).

```bash
ADMIN_PASSWORD="sua-senha-aqui" python app.py
```

## Instalar como app no celular (PWA)

O app tem suporte a PWA (Progressive Web App): depois de publicado com HTTPS, o aluno pode abrir o link no celular e usar a opção do navegador "Adicionar à tela inicial" (Android/Chrome) ou "Adicionar à Tela de Início" (iPhone/Safari). Isso cria um ícone com a logo da Elite Hapkido, que abre em tela cheia, sem barra de endereço.

Os arquivos necessários (`static/manifest.json`, `static/sw.js`, `static/icons/`) já estão no projeto e configurados em `templates/base.html`. Só funciona com HTTPS, então é preciso estar publicado (localhost também funciona para teste).

## Colocar no ar no Render (passo a passo)

1. No [Render](https://render.com), clique em **New → Web Service** e conecte este repositório (`Othilbh/App-Elite`).
2. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - Em **Environment**, adicione:
     - `ADMIN_PASSWORD` com a senha que o professor vai usar (troque o valor padrão `treino123`)
     - `DATABASE_URL` apontando para o seu Postgres (Supabase ou Render Postgres — ver seção acima). **Esse é o passo que resolve o problema de perder alunos/fotos/histórico a cada deploy.**
3. Depois do primeiro deploy, acesse a URL pública (tipo `app-elite.onrender.com`), entre como professor e cadastre os alunos reais.

⚠️ Se você pular a configuração do `DATABASE_URL`, o app funciona normalmente com SQLite, mas continua exposto a perder dados a cada novo deploy no plano gratuito do Render (o mesmo aviso de antes).

## Estrutura do projeto

```
App-Elite/
  app.py                  → toda a lógica (rotas, banco de dados, PIN, export)
  requirements.txt
  runtime.txt             → fixa a versão do Python usada no deploy (evita incompatibilidade com libs)
  static/
    css/style.css         → visual do app
    manifest.json         → configuração do PWA
    sw.js                 → service worker (cache só de assets estáticos)
    icons/                → ícones do PWA com a logo da Elite Hapkido
    uploads/               → fotos dos alunos ficam aqui (não versionado)
  templates/               → páginas HTML
  checkin.db               → banco SQLite local (só usado se DATABASE_URL não estiver definida; não versionado)
```

## Próximos passos possíveis

- Notificação (WhatsApp/e-mail) quando um check-in é confirmado ou fica pendente há muito tempo.
- Exportar também em PDF, além do Excel já disponível.
- Versão como app nativo (Android/iOS) reaproveitando esta mesma lógica de back-end.


