# Check-in de Treinos

Protótipo web para alunos registrarem presença nos treinos, com ranking semanal/mensal/anual e prêmio de fim de ano. Funciona no navegador do celular — não precisa instalar nada.

## Como funciona

- **Aluno**: entra no site, toca na própria foto, clica em "Registrar treino de hoje". O check-in fica pendente.
- **Professor**: entra em "Sou o professor" (senha padrão `treino123`), vê os check-ins pendentes e confirma ou rejeita cada um. Só check-ins confirmados contam no ranking.
- **Ranking**: página pública com abas Semana / Mês / Ano, mostrando todos os alunos ordenados por treinos confirmados.
- **Prêmio anual**: no painel do professor, em "Campeões", o botão "Fechar ano" registra o aluno com mais treinos confirmados no ano como campeão, criando um histórico (Hall da Fama) para os próximos anos.

## Rodar localmente (para testar)

Requer Python 3.9+.

```bash
cd treino-checkin
pip install -r requirements.txt
python app.py
```

Abra `http://localhost:5000` no navegador. Para outros aparelhos na mesma rede Wi-Fi acessarem, use o IP do seu computador, por exemplo `http://192.168.0.10:5000`.

Antes de usar de verdade, troque a senha do professor: defina a variável de ambiente `ADMIN_PASSWORD` (ou edite a constante `ADMIN_PASSWORD` no topo de `app.py`).

```bash
ADMIN_PASSWORD="sua-senha-aqui" python app.py
```

## Instalar como app no celular (PWA)

O app agora tem suporte a PWA (Progressive Web App): depois de publicado com HTTPS, o aluno pode abrir o link no celular e usar a opção do navegador "Adicionar à tela inicial" (Android/Chrome) ou "Adicionar à Tela de Início" (iPhone/Safari). Isso cria um ícone igual ao de um app normal, que abre em tela cheia, sem barra de endereço.

Não precisa fazer nada extra pra isso funcionar — já está configurado (`static/manifest.json`, `static/sw.js`, ícones em `static/icons/`). Só funciona com HTTPS, então é preciso estar publicado (localhost também funciona para teste).

## Colocar no ar para os alunos acessarem de qualquer lugar

Rodando só na sua máquina, o app só funciona na mesma rede Wi-Fi. Para os alunos acessarem pelo celular de qualquer lugar, hospede em um serviço gratuito/simples, por exemplo:

- **Render.com** (mais fácil): crie um "Web Service", conecte este código, comando de start `gunicorn app:app` (adicione `gunicorn` ao `requirements.txt`), defina a variável `ADMIN_PASSWORD`.
- **Railway.app**: parecido com o Render, também com plano gratuito.
- **PythonAnywhere**: bom para quem prefere algo mais manual/gratuito.

Em qualquer um deles, o app ganha uma URL pública (tipo `meuapp.onrender.com`) que você compartilha com os alunos.

⚠️ O banco de dados usado (SQLite, arquivo `checkin.db`) é simples e ótimo para uma turma. Em alguns serviços gratuitos os arquivos podem ser apagados a cada novo deploy — se isso acontecer com frequência, me avise que ajusto para usar um banco externo (Postgres, por exemplo).

## Estrutura do projeto

```
treino-checkin/
  app.py                  → toda a lógica (rotas, banco de dados)
  requirements.txt
  static/
    css/style.css         → visual do app
    uploads/               → fotos dos alunos ficam aqui
  templates/               → páginas HTML
  checkin.db               → banco de dados (criado automaticamente na 1ª execução)
```

## Próximos passos possíveis

- Login por PIN/senha individual do aluno (hoje qualquer um pode tocar na foto de qualquer aluno).
- Notificação (WhatsApp/e-mail) quando um check-in é confirmado ou fica pendente há muito tempo.
- Exportar ranking em PDF/planilha para divulgar o prêmio.
- Versão como app nativo (Android/iOS) reaproveitando esta mesma lógica de back-end.
