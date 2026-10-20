# Depuração e logs

O Twinverse grava logs de desenvolvedor para diagnosticar falhas de inicialização
e travamentos. Os logs são descartáveis, ficam apenas na sua máquina e não
aparecem na interface. Eles usam somente a biblioteca padrão do Python.

## Onde ficam os logs

Os logs seguem a [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/)
e ficam em `XDG_STATE_HOME`:

| Contexto | Diretório |
| --- | --- |
| Nativo | `~/.local/state/twinverse/logs` |
| Flatpak | `~/.var/app/io.github.mall0r.Twinverse/.local/state/twinverse/logs` |
| `XDG_STATE_HOME` definido | `$XDG_STATE_HOME/twinverse/logs` |

Dentro do Flatpak, as variáveis XDG exportadas pelas versões atuais já apontam
para os diretórios do aplicativo. Versões antigas do Flatpak podem não
exportá-las; nesse caso o Twinverse usa diretamente
`~/.var/app/$FLATPAK_ID/.local/state`, sem precisar de permissão extra nem de
`--persist`.

O diretório e os arquivos são criados apenas para o seu usuário (`0700` para
diretórios e `0600` para arquivos).

## O que há no diretório

```
logs/
├── twinverse.log       # log principal, com rotação
├── crash.log           # saída de travamento de baixo nível (faulthandler)
├── instances/          # um arquivo por inicialização de instância
│   ├── instance-01-20261020-140102-a8d1f372.log
│   └── latest.log -> instance-01-...log
└── helpers/            # logs de auxiliares, como o foco do overlay
    └── overlay-focus-a8d1f372-instance-01.log
```

O log principal mantém cinco arquivos rotacionados de 2 MiB por padrão. Os logs
de instância são mantidos por instância (os cinco mais recentes, por no máximo
14 dias) e os de auxiliares mantêm os dois mais recentes por execução. Os
limites podem ser alterados pelas variáveis de ambiente abaixo.

Cada registro inclui o identificador da execução e, quando disponível, a
instância e a fase (`launch`, `stop` ou `terminal`). Exemplo:

```
2026-10-20T14:01:02.349-03:00 INFO     src.services.instance [run_id=a8d1f372 instance=2 phase=launch] Launching instance 2
```

Os logs por instância também contêm a linha de comando (com argumentos secretos
comuns mascarados), os nomes das variáveis de ambiente, a saída do processo da
instância e o código de saída gravado quando a instância é encerrada.

## Executando com logs de depuração

A interface gráfica não tem controles de log. Inicie o Twinverse pelo terminal
ou edite o comando do `.desktop` se precisar de outro nível:

```bash
# Mensagens de depuração no console e no arquivo
twinverse --debug

# Somente avisos e erros no console; o arquivo continua em depuração
twinverse --quiet

# Escolhe explicitamente o nível do console
twinverse --log-level DEBUG

# Grava os logs fora do diretório XDG padrão
twinverse --log-dir /tmp/twinverse-debug --debug
```

Argumentos desconhecidos são repassados ao GTK, então flags do ambiente de
desktop ou do gerenciador de sessão continuam funcionando.

## Variáveis de ambiente

| Variável | Padrão | Significado |
| --- | --- | --- |
| `TWINVERSE_DEBUG` | não definida | `1` ativa depuração no console e no arquivo |
| `TWINVERSE_LOG_LEVEL` | `INFO` | Nível do console (nome ou número) |
| `TWINVERSE_LOG_FILE_LEVEL` | `DEBUG` | Nível do arquivo (nome ou número) |
| `TWINVERSE_LOG_DIR` | estado XDG | Diretório de logs alternativo |
| `TWINVERSE_LOG_FORMAT` | `text` | `text` ou `json` |
| `TWINVERSE_LOG_CONSOLE` | `1` | Use `0` para desativar a saída no console |
| `TWINVERSE_LOG_MAX_BYTES` | `2097152` | Tamanho do log principal antes da rotação |
| `TWINVERSE_LOG_BACKUPS` | `5` | Quantidade de logs principais rotacionados |
| `TWINVERSE_INSTANCE_LOG_MAX_BYTES` | `104857600` | Limite de tamanho de cada log de instância |

As opções de linha de comando têm prioridade sobre o ambiente.

## Diagnóstico sem abrir a janela

`--diagnostics` configura o log, imprime um relatório em stdout e encerra antes
de importar o GTK. Isso é útil quando a interface não inicia:

```bash
twinverse --diagnostics
twinverse --diagnostics --json > twinverse-diagnostics.json
```

O relatório inclui a versão do Twinverse, Python e plataforma, metadados do
Flatpak, tipo de sessão, caminhos XDG, tamanhos dos logs, dependências opcionais
disponíveis (`bwrap`, `pasta`, `gamescope`, `steam`) e o final dos logs
recentes. Ele não inclui o ambiente completo nem as variáveis das instâncias.

Ao relatar um problema, inclua o relatório e os arquivos relevantes do
diretório de logs. Revise o conteúdo antes de compartilhar: caminhos e linhas de
comando ainda podem identificar sua configuração, mesmo com senhas e tokens
comuns mascarados.

## Travamentos e exceções não tratadas

O Twinverse instala hooks de exceção e ativa o `faulthandler`. Tracebacks do
Python vão para `twinverse.log`; travamentos nativos e abortos graves gravam um
stack do Python em `crash.log`, incluindo o estado de todas as threads. Uma
falha em um processo filho não derruba as outras instâncias, e a saída permanece
no log daquela instância.

Quando o próprio Twinverse morre, as instâncias do Steam não são encerradas: o
sandbox roda fora do grupo de processos da aplicação, então os clientes
continuam rodando sem ninguém consumindo a saída deles. Os logs param de
crescer nesse momento e as instâncias precisam ser fechadas manualmente.

O sistema de logs nunca usa um pipe para a saída da instância: o processo filho
grava diretamente no arquivo, então uma sessão barulhenta do Steam ou do Proton
não pode encher um pipe e congelar a instância. No caminho Flatpak, os pipes do
host são drenados em threads de fundo para o mesmo arquivo.

## Privacidade

Os logs são locais e não são enviados automaticamente. O Twinverse mascara
formatos comuns de segredo (`PASSWORD=...`, `TOKEN=...`, cabeçalhos
Authorization, credenciais em URLs e flags de linha de comando semelhantes)
antes de gravar. Isso é uma proteção de melhor esforço, não uma garantia: apague
os logs se eles contiverem informações que você não quer compartilhar.

## Observações sobre Flatpak

Nenhuma alteração no manifesto é necessária para os logs, e nenhuma permissão
extra de sistema de arquivos é adicionada. O diretório de logs fica dentro do
diretório de estado do próprio aplicativo, que o Flatpak mantém entre
atualizações. O log do auxiliar é montado no sandbox da instância em
`/tmp/twinverse-logs` somente enquanto o auxiliar de foco do overlay está
ativado.
