# Agenda do Salão

Agenda online para salão de beleza, **serverless na AWS**: cada salão entra com login, cadastra
serviços e profissionais, define o horário de funcionamento e agenda clientes sem chance de
horário duplicado.

```
Navegador ──► CloudFront ──► S3 (site estático: HTML/CSS/JS, sem build)
    │
    └─► API Gateway (HTTP API, valida o token JWT do Cognito) ──► Lambda (Python) ──► DynamoDB
```

| Parte | Onde | Tamanho |
|---|---|---|
| Backend (regras + API) | `backend/src/agenda/` | 669 linhas |
| Frontend | `frontend/` | ~535 linhas |
| Testes do backend | `backend/tests/` | 142 testes |
| Teste de navegador | `e2e/` | Chromium de verdade |
| Infraestrutura | `infra/` (Terraform) | fora da contagem |
| CI/CD | `.github/workflows/` | fora da contagem |

## Como funciona (o que importa)

- **Um salão = um usuário do Cognito.** O id do salão (`sub` do token) vem do token já validado
  pelo API Gateway, **nunca do corpo da requisição**. Todo item do DynamoDB leva `PK = SALAO#<id>`.
- **Sem horário duplicado, mesmo com cliques simultâneos.** Cada atendimento grava, numa
  transação só, o agendamento e uma "trava" por bloco de 15 minutos. Se qualquer trava já existe,
  nada é gravado e a resposta é "horário ocupado". Atendimentos que apenas encostam (10:00–11:00 e
  11:00–12:00) não conflitam.
- Horários são de Brasília (UTC-3), em passos de 15 min. Dia, hora de abrir/fechar e dias de
  funcionamento são configuráveis. Não se agenda no passado nem fora do expediente.
- O agendamento guarda uma **cópia** do nome, preço e duração do serviço: mudar o preço depois não
  altera o histórico.

## Rodar sem AWS (opcional: o CI do GitHub já roda tudo isto)

```bash
pip install pytest playwright && playwright install chromium
python -m pytest -q backend/tests      # regras de negócio e API (usa DynamoDB falso)
python e2e/teste_e2e.py                # abre o site num navegador e usa a API de verdade
python e2e/servidor_local.py           # serve o site + API em memória em http://127.0.0.1:8765
```

O teste de navegador cobre login com troca de senha, cadastros, agendamento, conflito,
cancelamento, proteção contra HTML injetado e a mesma política de segurança (CSP) do CloudFront.

## Ambientes e publicação (tudo pelo GitHub, sem terminal)

São dois ambientes, **cada um numa conta AWS diferente**:

| Ambiente | Quando publica | Environment no GitHub | Recursos na AWS |
|---|---|---|---|
| `dev` | **sozinho**, a cada push na branch `dev` | `dev` | `agenda-salao-dev-*` |
| `prod` | **só quando alguém aperta o botão** (Actions → *Deploy produção* → *Run workflow*, na `main`) | `producao` | `agenda-salao-prod-*` |

Fluxo: trabalha na `dev` (deploy automático) → abre PR `dev` → `main` (roda o CI) → faz o merge →
publica em produção pelo botão. O workflow de produção recusa rodar fora da `main` e pede que você
digite `producao` para confirmar. Merge na `main` **não** publica nada.

### Passo 1: um usuário IAM para o GitHub, em cada conta AWS (console da AWS, no navegador)

1. IAM → *Policies* → *Create policy* → aba **JSON** → cole o conteúdo de
   [`docs/politica-iam-deploy.json`](docs/politica-iam-deploy.json) → nome `agenda-salao-deploy`.
   Ela só permite mexer em recursos cujo nome começa com `agenda-salao-`.
2. IAM → *Users* → *Create user* → nome `github-deploy-agenda-salao`, **sem** acesso ao console →
   anexe a política `agenda-salao-deploy`.
3. Abra o usuário → *Security credentials* → *Create access key* → caso de uso *Application running
   outside AWS* → copie o **Access key ID** e o **Secret access key** (o segredo só aparece agora).
4. Repita nas duas contas (dev e produção). Anote também o **número da conta** (12 dígitos, no menu
   do canto superior direito).

### Passo 2: Environments no GitHub (Settings → Environments)

Crie `dev` e `producao`. Em **cada um**, cadastre (com os valores daquela conta):

| Tipo | Nome | Exemplo | Para que serve |
|---|---|---|---|
| **Secret** | `AWS_ACCESS_KEY_ID` | `AKIA...` | chave do usuário IAM daquela conta |
| **Secret** | `AWS_SECRET_ACCESS_KEY` | `wJalr...` | segredo do usuário IAM |
| Variable | `AWS_ACCOUNT_ID` | `123456789012` | conferência: se a chave for de outra conta, o deploy **para antes de publicar** |
| Variable | `AWS_REGION` | `sa-east-1` | região |

Só isso. O bucket do estado do Terraform (`agenda-salao-estado-<conta>`) é criado pelo próprio
deploy na primeira vez. Recomendado no `producao`: *Required reviewers* (você) e *Deployment
branches* = só `main`.

### Passo 3: publicar

- **dev:** crie a branch `dev` (no GitHub: botão de branches → digite `dev` → *Create branch*). A
  criação já dispara o primeiro deploy. Acompanhe em *Actions*; o endereço do site aparece no
  resumo da execução.
- **produção:** *Actions* → *Deploy produção* → *Run workflow* (branch `main`) → digite `producao`.

### Passo 4: criar o login de um salão (não há cadastro aberto, de propósito)

*Actions* → *Criar usuário do salão* → *Run workflow* → escolha o ambiente e digite o e-mail. O
Cognito envia uma senha temporária por e-mail; no primeiro acesso o site pede a senha nova. Os
usuários de `dev` e `prod` são separados.

> Se algum passo falhar por falta de permissão da política IAM, o erro do Actions diz qual ação foi
> negada: é só incluí-la em `docs/politica-iam-deploy.json` e atualizar a política na AWS.

## Segurança e custo

- Tabela criptografada, com backup contínuo (PITR) e proteção contra exclusão em `prod`.
- A Lambda só pode ler/gravar/apagar itens da própria tabela. O API Gateway limita a taxa
  (`limite_por_segundo`) para conter abuso e custo.
- O site só conversa com ele mesmo, o Cognito e a API (CSP) e não pode ser colocado em iframe.
- O deploy usa chaves de acesso de um usuário IAM **só com as permissões deste projeto** (política
  em `docs/`), guardadas como *secrets* do Environment (o GitHub as esconde nos logs). Chaves
  duram até serem trocadas: **gire-as de tempos em tempos** (IAM → usuário → criar nova chave →
  atualizar o secret → apagar a antiga), nunca as coloque em arquivo do repositório e proteja a
  branch `main`. O caminho mais seguro, que dispensa chaves, é OIDC (login temporário); dá para
  migrar depois.
- Custo: sem tráfego, perto de zero (tudo é por uso). O que pode cobrar mesmo parado é pouco:
  logs e armazenamento no S3.

## O que ainda falta (de propósito: é só a base)

- Página pública para a cliente agendar sozinha e lembretes por WhatsApp/SMS.
- Cadastro aberto de salões, cobrança da assinatura e política de privacidade (LGPD).
- Domínio próprio com certificado (ACM) e alarmes no CloudWatch.
- O Terraform e as Actions **não foram executados** no ambiente onde o código foi escrito (sem
  Terraform nem AWS): o primeiro deploy na `dev` é o teste de verdade. Se falhar, copie o erro do
  Actions e corrija.
