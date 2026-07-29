# Elite Hapkido — Check-in de Treinos

App para os alunos registrarem presença nos treinos, com ranking semanal/mensal/anual e prêmio de fim de ano. Funciona no navegador do celular — não precisa instalar nada (e pode ser "instalado" como PWA, ver abaixo).

## Como funciona

- **Aluno**: entra no site, toca na própria foto, digita seu **PIN de 4 números** e clica em "Registrar treino de hoje". O check-in fica pendente.
- **Professor**: entra em "Sou o professor" (senha padrão `treino123`), vê os check-ins pendentes e confirma ou rejeita cada um. Só check-ins confirmados contam no ranking.
- **Ranking**: página pública com abas Semana / Mês / Ano, mostrando todos os alunos ordenados por treinos confirmados.
- **Prêmio anual**: no painel do professor, em "Campeões", o botão "Fechar ano" registra o aluno com mais treinos confirmados no ano como campeão, criando um histórico (Hall da Fama) para os próximos anos.

### PIN individual do aluno

Cada aluno tem um PIN de 4 números, para que só ele consiga fazer check-in em seu próprio nome (antes, qualquer pessoa podia tocar na foto de outro aluno).

- Ao cadastrar um aluno, você pode digitar um PIN específico ou deixar em branco para o sistema gerar um automaticamente.
- O PIN de cada aluno aparece na lista em **Painel → Alunos** — é aí que você pega o número para repassar a ele (pessoalmente ou por WhatsApp).
- Se o aluno esquecer o PIN, use o botão **"Gerar novo PIN"** na mesma tela.
- Alunos cadastrados antes dessa funcionalidade existir continuam entrando sem PIN normalmente (não trava ninguém de fora).

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

O app tem suporte a PWA (Progressive Web App): depois de publicado com HTTPS, o aluno pode abrir o link no celular e usar a opção do navegador "Adicionar à tela inicial" (Android/Chrome) ou "Adicionar à Tela de Início" (iPhone/Safari). Isso cria um ícone igual ao de um app normal, que abre em tela cheia, sem barra de endereço.

Os arquivos necessários (`static/manifest.json`, `static/sw.js`, `static/icons/`) já estão no projeto e configurados em `templates/base.html`. Só funciona com HTTPS, então é preciso estar publicado (localhost também funciona para teste).

## Colocar no ar no Render (passo a passo)

1. No [Render](https://render.com), clique em **New → Web Service** e conecte este repositório (`Othilbh/App-Elite`).
2. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - Em **Environment**, adicione a variável `ADMIN_PASSWORD` com a senha que o professor vai usar (troque o valor padrão `treino123`).
3. **⚠️ Passo crítico — disco persistente:** por padrão, o Render apaga os arquivos gravados pelo app (o banco `checkin.db` e as fotos em `static/uploads/`) a cada novo deploy ou reinício. Para as fotos e o histórico de check-ins não sumirem:
   - No plano **Starter** (pago, ~US$7/mês) ou superior, vá em **Disks** no painel do serviço e adicione um disco persistente montado em `/opt/render/project/src` (ou ajuste `DB_PATH`/`UPLOAD_FOLDER` em `app.py` para apontar para o caminho do disco, ex: `/var/data`).
   - No plano **Free**, não há disco persistente — o app funciona, mas cada novo deploy zera alunos, fotos e histórico. Serve bem para testar o app com a turma antes de decidir se vale investir no plano pago.
4. Depois do primeiro deploy, acesse a URL pública (tipo `app-elite.onrender.com`), entre como professor e cadastre os alunos reais.

## Estrutura do projeto

```
App-Elite/
  app.py                  → toda a lógica (rotas, banco de dados, PIN)
  requirements.txt
  static/
    css/style.css         → visual do app
    manifest.json         → configuração do PWA
    sw.js                 → service worker (cache só de assets estáticos)
    icons/                → ícones do PWA (192px, 512px, maskable)
    uploads/               → fotos dos alunos ficam aqui (não versionado)
  templates/               → páginas HTML
  checkin.db               → banco de dados (criado automaticamente na 1ª execução, não versionado)
```

## Próximos passos possíveis

- Notificação (WhatsApp/e-mail) quando um check-in é confirmado ou fica pendente há muito tempo.
- Exportar ranking em PDF/planilha para divulgar o prêmio.
- Migrar de SQLite para Postgres (Render oferece um banco Postgres gerenciado gratuito) para não depender de disco persistente e ter mais robustez.
- Versão como app nativo (Android/iOS) reaproveitando esta mesma lógica de back-end.

