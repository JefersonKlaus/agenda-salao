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

## Rodar sem AWS (desenvolvimento)

```bash
pip install pytest playwright && playwright install chromium
python -m pytest -q backend/tests      # regras de negócio e API (usa DynamoDB falso)
python e2e/teste_e2e.py                # abre o site num navegador e usa a API de verdade
python e2e/servidor_local.py           # serve o site + API em memória em http://127.0.0.1:8765
```

O teste de navegador cobre login com troca de senha, cadastros, agendamento, conflito,
cancelamento, proteção contra HTML injetado e a mesma política de segurança (CSP) do CloudFront.

## Publicar na AWS pela primeira vez

1. **Bucket do estado do Terraform** (uma vez, à mão):
   ```bash
   aws s3api create-bucket --bucket SEU-BUCKET-DE-ESTADO --region sa-east-1 \
     --create-bucket-configuration LocationConstraint=sa-east-1
   aws s3api put-bucket-versioning --bucket SEU-BUCKET-DE-ESTADO --versioning-configuration Status=Enabled
   ```
2. **Primeiro `apply` na sua máquina** (com credenciais de administrador), porque ele cria a role
   que o GitHub vai usar depois:
   ```bash
   cd infra
   cp terraform.tfvars.exemplo terraform.tfvars   # preencha repositorio_github e bucket_estado
   terraform fmt -recursive                       # ajusta o formato uma vez e faça commit
   terraform init -backend-config="bucket=SEU-BUCKET-DE-ESTADO" \
     -backend-config="key=agenda-salao/prod.tfstate" -backend-config="region=sa-east-1" \
     -backend-config="use_lockfile=true"
   terraform apply
   ```
3. **No GitHub** (Settings → Environments → criar `producao`, com *Required reviewers*) e em
   Settings → Variables, crie: `AWS_REGION` (`sa-east-1`), `AWS_ROLE_ARN` (saída
   `role_de_deploy_arn`), `TF_STATE_BUCKET`, e `CRIAR_PROVEDOR_OIDC` = `false` se o primeiro
   `apply` criou o provedor (ou se a conta já tinha).
4. Dê `push` na `main`: roda os testes e, se passarem, o deploy aplica o Terraform, gera
   `frontend/js/config.js`, envia o site ao S3 e limpa o cache do CloudFront.
5. **Criar o login de um salão** (não há cadastro aberto de propósito):
   ```bash
   aws cognito-idp admin-create-user --region sa-east-1 --user-pool-id <cognito_user_pool_id> \
     --username dona@salao.com --user-attributes Name=email,Value=dona@salao.com
   ```
   O Cognito envia uma senha temporária por e-mail; no primeiro acesso o site pede a senha nova.

## Segurança e custo

- Tabela criptografada, com backup contínuo (PITR) e proteção contra exclusão em `prod`.
- A Lambda só pode ler/gravar/apagar itens da própria tabela. O API Gateway limita a taxa
  (`limite_por_segundo`) para conter abuso e custo.
- O site só conversa com ele mesmo, o Cognito e a API (CSP) e não pode ser colocado em iframe.
- O deploy entra na AWS por OIDC, sem chave guardada no GitHub, e só pelo ambiente `producao`.
  **Atenção:** a role de deploy pode alterar a si mesma (o Terraform a gerencia), então proteja a
  branch `main` e exija aprovação no ambiente.
- Custo: sem tráfego, perto de zero (tudo é por uso). O que pode cobrar mesmo parado é pouco:
  logs e armazenamento no S3.

## O que ainda falta (de propósito: é só a base)

- Página pública para a cliente agendar sozinha e lembretes por WhatsApp/SMS.
- Cadastro aberto de salões, cobrança da assinatura e política de privacidade (LGPD).
- Domínio próprio com certificado (ACM) e alarmes no CloudWatch.
- O Terraform e as Actions **não foram executados** no ambiente onde o código foi escrito (sem
  Terraform nem AWS): rode `terraform validate` e o primeiro `apply` e me diga o que reclamar.
