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
├── crash.log.1         # o travamento da sessão anterior
├── instances/          # um arquivo por inicialização de instância
│   ├── instance-01-20261020-140102-a8d1f372.log
│   └── latest.log -> instance-01-...log
└── helpers/            # logs de auxiliares, como o foco do overlay
    └── overlay-focus-a8d1f372-instance-01.log
```

O log principal mantém cinco arquivos rotacionados de 2 MiB por padrão. Os logs
de instância são mantidos por instância (os cinco mais recentes, por no máximo
14 dias) e os de auxiliares mantêm os dois mais recentes por execução. Um
limite total de 256 MiB para o diretório inteiro apaga os arquivos mais
antigos quando ele é atingido. Os limites podem ser alterados pelas variáveis
de ambiente abaixo.

O log de travamentos é rotacionado quando o aplicativo inicia: o travamento da
sessão anterior fica em `crash.log.1` e um `crash.log` novo é criado. Os dois
arquivos juntos sempre têm tamanho limitado.

Cada registro inclui o identificador da execução e, quando disponível, a
instância e a fase (`launch`, `stop` ou `terminal`). Exemplo:

```
2026-10-20T14:01:02.349-03:00 INFO     src.services.instance [run_id=a8d1f372 instance=2 phase=launch] Launching instance 2
```

Os logs por instância também contêm a linha de comando (com argumentos secretos
comuns mascarados), os nomes das variáveis de ambiente, a saída do processo da
instância e o código de saída gravado quando a instância é encerrada. Cada
instância grava no seu próprio arquivo, então a saída continua sendo registrada
mesmo quando o próprio Twinverse morre.

## Limpeza dos logs

Os logs são descartáveis. Para começar de um diretório vazio, sem abrir a
interface:

```bash
twinverse --clear-logs
```

A limpeza também acontece sozinha: os arquivos rotacionados são substituídos
quando chegam ao limite de tamanho, os logs de instância e de auxiliar expiram
e o tamanho total do diretório é mantido abaixo do limite informado abaixo.

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
| `TWINVERSE_LOG_KEEP_INSTANCES` | `5` | Logs de instância mantidos por instância |
| `TWINVERSE_LOG_KEEP_HELPERS` | `2` | Logs de auxiliar mantidos por execução |
| `TWINVERSE_LOG_MAX_AGE_DAYS` | `14` | Idade do log mais antigo que é mantido |
| `TWINVERSE_LOG_MAX_TOTAL_MB` | `256` | Limite de tamanho do diretório de logs inteiro |

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

Quando o próprio Twinverse morre, as instâncias do Steam não são encerradas: elas
rodam fora do grupo de processos da aplicação, então os clientes continuam
rodando. Os logs continuam sendo escritos, porque cada instância grava no seu
próprio arquivo.

A sessão seguinte encontra essas instâncias. O Twinverse guarda o que lançou em
`instances.json`, dentro do diretório de estado do XDG, e na inicialização
verifica se os processos continuam vivos e continuam sendo os que ele lançou. As
instâncias que sobreviveram aparecem como em execução, e o botão de parar
encerra cada uma delas. Um grupo de processos que o sistema reaproveitou nesse
meio tempo nunca é tocado.

O sistema de logs nunca usa um pipe para a saída da instância: o processo filho
grava diretamente no arquivo, então uma sessão barulhenta do Steam ou do Proton
não pode encher um pipe e congelar a instância. O caminho do Flatpak usa o
mesmo redirecionamento, então a saída de uma instância que sobrevive ao
aplicativo nunca é perdida.

### A janela nunca aparece no Wayland

Um AppImage pode morrer antes de a janela existir por um motivo fora do
Twinverse: o GTK que ele empacota. O GTK 4.16 se liga à versão do
`linux-dmabuf` que o compositor anuncia, mas só implementa o feedback da
versão 5. Em um compositor que anuncia a versão 6, como o KWin 6.8, nenhum
evento `main_device` chega e o primeiro evento `tranche_done` desreferencia um
ponteiro nulo, então o processo morre com `SIGSEGV` dentro de `Gtk.init()`.

O `crash.log` mostra a falha em `gi/overrides/Gtk.py`, antes de qualquer código
da aplicação rodar. O Flatpak não é afetado, porque o runtime do GNOME traz um
GTK atual. Se um AppImage ainda empacota o GTK 4.16, execute-o no backend X11,
que nunca se liga à interface do Wayland:

```bash
GDK_BACKEND=x11 ./Twinverse-x86_64.AppImage
```

`GDK_DISABLE=dmabuf` não ajuda: o display se liga à interface antes de
consultar essa configuração.

### O cursor muda dentro da janela

A aplicação nunca define um cursor. O GTK escolhe o cursor a partir do tema
definido em `gtk-cursor-theme-name` e do tamanho em `gtk-cursor-theme-size`,
e usa o cursor default interno quando o tema não é encontrado.

A aplicação reaplica o tema de cursor configurado nas configurações do
usuário no startup e quando a configuração `gtk-cursor-theme-name` muda, para
que o tema configurado seja resolvido de novo em vez de ficar no cursor
default. Isso cobre o AppImage e o Flatpak, que trazem seus próprios builds do
GTK, e mantém o cursor que o usuário escolheu.

## Quando o cliente da Steam não abre

O sandbox pode subir enquanto o cliente da Steam nunca aparece, deixando uma
janela do compositor que nunca é desenhada. O Twinverse acompanha a
inicialização de cada instância que lança e diz ao usuário o que está
acontecendo:

- enquanto o cliente sobe, aparece uma mensagem sobre a janela;
- quando o cliente informa que abriu, a mensagem é trocada por uma confirmação
  curta;
- quando o cliente da Steam escreve uma linha fatal no log dele, ou quando a
  instância para sozinha, a mensagem diz o que o Steam reportou e o motivo vai
  para o `twinverse.log` como aviso.

Não há prazo em nenhum desses casos. Uma máquina lenta leva o tempo que
precisar, e a mensagem fica até o cliente da Steam dizer que está de pé.

A checagem nunca confunde as instâncias. Só aceita um cliente da Steam que
pertence ao grupo de processos daquela instância, então o cliente de outra
instância, e o Steam do usuário, nunca são tomados como o nosso.

Enquanto o cliente arranca, a linha da instância mostra um indicador a girar e
o tooltip diz o que a Steam está a fazer, tirado do log do cliente. Uma Steam
que se atualiza pode demorar minutos, e o indicador faz claro que ainda está
a acontecer alguma coisa. A janela só é minimizada depois de todas as
instâncias serem confirmadas como abertas.

As mensagens da aplicação são mostradas sobre a janela. Quando a janela está
minimizada, ou em segundo plano atrás de um jogo, a mesma mensagem também é
mostrada como notificação de desktop, para que uma falha não passe
despercebida enquanto se joga. A notificação usa o portal de notificações, que
não precisa de permissões extra.

Os botões da interface seguem a mesma regra. Uma instância só mostra "Stop"
depois do seu cliente da Steam ser confirmado como de pé, e só volta para
"Start" depois da instância ser confirmada como encerrada. Enquanto a
instância está a arrancar, o botão mostra "Cancel", que encerra a instância
que nunca subiu; enquanto está a parar, o botão não pode ser premido. O botão
do rodapé só vira "Stop" quando todas as instâncias que ele segue estão
confirmadas em execução, assim um arranque que ainda está a acontecer não é
interrompido a meio. Um cliente que nunca subiu não deixa nada a preservar,
então o que sobrou é encerrado e a instância volta para "Start".

O log do próprio cliente da Steam fica na home da instância, em
`.local/share/Steam/logs/console-linux.txt`. Esse arquivo tem o motivo da
falha nas palavras do Steam, e a mensagem da interface o cita.

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
