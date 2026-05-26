# Deploy 24 horas

Este bot so fica 24 horas no ar se rodar em uma hospedagem com URL HTTPS fixa.
Ngrok + Flask local servem para teste, mas param quando o PC desliga.

## Caminho recomendado: Railway

Use Railway com um volume persistente para guardar o SQLite.

### 1. Suba o projeto para um repositorio privado

Crie um repositorio privado no GitHub e envie a pasta `whatsapp-leads-bot`.

Nao suba o arquivo `.env`.

O arquivo `contatos_conhecidos_producao.csv` contem sua lista inicial de contatos
conhecidos. Ele deve ir somente para repositorio privado.

### 2. Crie o projeto no Railway

1. Acesse o Railway.
2. Crie um novo projeto a partir do repositorio do GitHub.
3. Selecione a pasta do bot, se o repositorio tiver mais de uma pasta.
4. Confirme que o comando de inicio ficou:

```bash
gunicorn app:app -c gunicorn.conf.py
```

O arquivo `railway.json` ja configura esse comando e o healthcheck em `/healthz`.

### 3. Crie um volume persistente

1. No projeto do Railway, crie um volume.
2. Conecte o volume ao servico do bot.
3. Use este mount path:

```text
/data
```

### 4. Configure as variaveis de ambiente

No Railway, adicione as variaveis:

```env
META_ACCESS_TOKEN=token_copiado_do_dualhook
WHATSAPP_PHONE_NUMBER_ID=phone_number_id_da_conta
WHATSAPP_VERIFY_TOKEN=o_mesmo_verify_token_do_dualhook
WHATSAPP_API_VERSION=v25.0
OWNER_WHATSAPP_NUMBER=55DDDNUMERO_DO_RESPONSAVEL
META_APP_SECRET=
DATABASE_PATH=/data/leads.db
KNOWN_CONTACTS_CSV=contatos_conhecidos_producao.csv
QUESTIONNAIRE_FILE=questionario.json
DEBUG=false
```

Nao coloque aspas nos valores.

### 5. Pegue a URL fixa do Railway

Depois do deploy, abra:

```text
https://sua-url-do-railway.up.railway.app/healthz
```

Se aparecer `ok`, o servidor esta vivo.

O webhook sera:

```text
https://sua-url-do-railway.up.railway.app/webhook
```

### 6. Atualize o Dualhook

No Dualhook, em Webhook Override:

1. Troque a URL antiga do ngrok pela URL do Railway terminando em `/webhook`.
2. Mantenha o mesmo Verify Token configurado no Railway.
3. Salve as alteracoes.
4. Use o botao de teste/verificacao.

Depois disso, pode desligar o PC. As mensagens passam a chegar no Railway.

## Alternativa: Render

Render tambem funciona, mas para este projeto use plano pago com persistent disk.
O plano gratuito pode dormir depois de inatividade e nao preserva o SQLite local.

Configuracao no Render:

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app -c gunicorn.conf.py
Health Check Path: /healthz
```

Persistent disk:

```text
Mount path: /opt/render/project/src/data
DATABASE_PATH=/opt/render/project/src/data/leads.db
```

## Backup dos contatos conhecidos

Para exportar a lista atual de contatos conhecidos:

```bash
python listar_contatos.py --export contatos_conhecidos_producao.csv
```

Para teste local, voce ainda pode remover ou adicionar contatos com:

```bash
python gerenciar_contatos.py buscar 5511999999999
python gerenciar_contatos.py adicionar 5511999999999 "Nome Teste"
python gerenciar_contatos.py remover 5511999999999
```

Em producao, o banco vivo sera o SQLite do volume configurado em `DATABASE_PATH`.
