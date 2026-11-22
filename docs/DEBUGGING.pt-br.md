<p align="right">
  <a href="https://mall0r.github.io/Twinverse/?lang=pt#cli-debugging"><img src="https://img.shields.io/badge/Docs-GitHub%20Pages-1f6feb.svg?logo=githubpages&logoColor=white" alt="Documentação Interativa"/></a>
  <a href="DEBUGGING.md"><img src="https://img.shields.io/badge/en-US-darkblue.svg" alt="English"/></a>
  <a href="DEBUGGING.pt-br.md"><img src="https://img.shields.io/badge/pt-BR-darkgreen.svg" alt="Portuguese"/></a>
</p>

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
| `TWINVERSE_UINPUT_LOG` | não definida | Defina como `1` para ativar logs detalhados de `twinverse-input-bridge`, `libtwinverse_uinput.so` e `libtwinverse_udev.so` no log da instância |

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

## Virtual uinput, Steam Input e hotplug de controles

Quando os artefatos nativos em Rust estão presentes (sempre empacotados no
Flatpak e no AppImage, e compilados em `res/native/` pelo `./run.sh` ou
`make build-native`), o Twinverse prepara um pequeno diretório de runtime
dentro da home de cada jogador:

```text
<home_N>/.tw-in/
├── bin/
│   └── twinverse-input-bridge   # supervisor de hotplug e lista hidraw no host
├── lib64/
│   ├── libtwinverse_uinput.so   # interpositor 64 bits de /dev/uinput + event + hidraw
│   └── libtwinverse_udev.so     # shim libudev 64 bits (evdev virtual + hotplug hidraw)
├── lib32/
│   ├── libtwinverse_uinput.so   # interpositor 32 bits (para o cliente Steam 32 bits)
│   └── libtwinverse_udev.so     # shim libudev 32 bits
└── sock/
    ├── tw_event3000.sock        # socket do controle físico encaminhado pelo bridge
    ├── tw_event2000.sock        # sockets de controles virtuais do Steam Input (2000+)
    └── tw_hidraw.allow          # lista dinâmica (uma linha por nó) de hidraw permitidos
```

Pontos úteis para diagnóstico:

- **Logs detalhados da camada nativa:** Defina `TWINVERSE_UINPUT_LOG=1` nas
  **Environment variables** do jogador (para `libtwinverse_uinput.so` / `libtwinverse_udev.so`)
  ou no ambiente antes de iniciar o Twinverse (para registrar também desconexões,
  reconexões e transições da lista `hidraw` no `twinverse-input-bridge`). A saída
  fica gravada em `logs/instances/instance-NN-*.log`.
- **`LD_PRELOAD` adiado:** O Gamescope nunca recebe `LD_PRELOAD`. O Twinverse
  injeta `TWINVERSE_VIRTUAL_UINPUT=1`, `TWINVERSE_UINPUT_SOCKET_DIR`,
  `TWINVERSE_PHYSICAL_BRIDGE` e `TWINVERSE_HIDRAW_FILTER` na sandbox e usa
  `GAMESCOPE_RUNTIME_SETUP` para ativar o `LD_PRELOAD` apenas no Steam e nos
  jogos filhos.
- **Staging verificado por conteúdo (Flatpak/OSTree):** Os arquivos em `~/.tw-in/`
  são comparados byte a byte (não apenas por tamanho e `mtime`), garantindo que
  atualizações do Flatpak sempre renovem as bibliotecas nativas mesmo quando o
  OSTree define `mtime` como epoch 0.
- **Detecção de fallback:** Se o `twinverse.log` indicar que as bibliotecas
  nativas de uinput virtual não foram encontradas (por exemplo, ao rodar do
  código-fonte sem Rust), o Twinverse usa automaticamente o fallback com
  bind-mounts estáticos de `/dev/input/eventX` e máscara estática de `/dev/hidraw*`.

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

### As janelas trocam de posição ao abrir ou fechar um jogo

O layout do KWin associa cada janela a uma instância explícita, não à ordem
de `workspace.windowList()`. O launcher coloca `TWINVERSE_KWIN_INSTANCE` no
ambiente do Gamescope. Um serviço D-Bus do Twinverse identifica a instância
pelo PID informado pelo KWin; no Flatpak, a consulta usa o PID do host.
O título do jogo, o objeto da janela e o PID podem mudar sem mudar a posição
reservada para aquela instância.

A quantidade de divisões vem da seleção de jogadores, não da quantidade de
janelas visíveis naquele instante. Uma janela que desaparece deixa seu espaço
reservado: as outras não são deslocadas ou ampliadas. Mudanças externas de
geometria são corrigidas pelo script. Janelas de Gamescope que não pertencem
às instâncias selecionadas são ignoradas.

Mantenha o Twinverse aberto, mesmo minimizado, para identificar janelas novas.
O log de depuração registra PID e instância, sem registrar o ambiente do
processo. O KWin também imprime a associação de instância e posição nos seus
próprios logs. Ao alterar o layout, o script anterior é descarregado pelo
nome do plugin; IDs numéricos não são nomes válidos para `unloadScript`.

### O cursor muda dentro da janela

A aplicação nunca define um cursor. O GTK escolhe o cursor a partir do tema
definido em `gtk-cursor-theme-name` e do tamanho em `gtk-cursor-theme-size`,
e usa o cursor default interno quando o tema não é encontrado.

A aplicação reaplica o tema de cursor configurado nas configurações do
usuário no startup e quando a configuração `gtk-cursor-theme-name` muda, para
que o tema configurado seja resolvido de novo em vez de ficar no cursor
default. Mas reaplicar o valor não resolve quando o próprio GTK lê o tema
errado: no AppImage, o GTK 4.16 usava GSettings sem o backend de configurações
do host e obtinha `Adwaita` em vez do tema escolhido no KDE. Isso acontece
também no Wayland e não indica uma troca para X11.

O launcher do AppImage habilita o portal de configurações (`GDK_DEBUG=portals`)
para receber o tema do cursor, tamanho e fonte do desktop, incluindo mudanças
durante a execução. Os temas do host têm prioridade sobre o fallback empacotado.
Para depuração, `GDK_DEBUG=no-portals` desabilita essa integração explicitamente.

### Fontes e ícones diferentes apenas no AppImage

O AppImage usa `/etc/fonts` do host e respeita `FONTCONFIG_FILE` e
`FONTCONFIG_PATH` definidos pelo usuário. A configuração empacotada só é usada
se a configuração do host estiver ausente. O fontconfig empacotado é atualizado
para interpretar também as regras das distribuições recentes.

O GTK 4.16 também não marcava como simbólicos os ícones encontrados diretamente
no diretório de recursos `icons/`, deixando o preenchimento branco do SVG fixo
no tema claro. Um patch exclusivo do AppImage corrige essa classificação.
O build testa os pixels dos ícones com foreground preto e branco usando o GTK
que será empacotado (via `scripts/appimage/check-appearance.rs`), sem alterar
os SVGs usados pelos outros formatos.

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

A checagem nunca confunde as instâncias. Ela acompanha a árvore de processos
do `steamwebhelper` (SteamRT3) restrita ao grupo de processos daquela instância
(e encerra descendentes `setsid` com segurança ao parar), então o cliente de
outra instância e o Steam principal do usuário nunca são confundidos ou afetados.

Enquanto o cliente inicia ou se atualiza (o que pode levar alguns minutos),
a linha do jogador mostra um indicador giratório e o painel Player Setup exibe
uma linha simples de log em tempo real logo acima do botão **Start player** /
**Install Steam**, atualizada a cada segundo a partir de
`.local/share/Steam/logs/console-linux.txt`. A última linha é preservada em
intervalos silenciosos e limpa assim que a instância fica `Running` ou para.
A janela só é minimizada depois que todas as instâncias são confirmadas como
abertas.

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
