<p align="right">
  <a href="https://github.com/mall0r/Twinverse/blob/main/docs/GUIDE.md"><img src="https://img.shields.io/badge/EN-🇬🇧-darkblue.svg" alt="English"/></a>
  <a href="https://github.com/mall0r/Twinverse/blob/main/docs/GUIDE.pt-br.md"><img src="https://img.shields.io/badge/PT-🇧🇷-darkgreen.svg" alt="Portuguese"/></a>
  <a href="https://github.com/mall0r/Twinverse/blob/main/docs/GUIDE.es.md"><img src="https://img.shields.io/badge/ES-🇪🇸-darkred.svg" alt="Spanish"/></a>
</p>

# Guia do Twinverse

Bem-vindo ao guia do Twinverse! Este documento irá guiá-lo pelo processo de configuração e uso do aplicativo Twinverse para executar múltiplas instâncias do Steam.

## 1. Número de Instâncias

Primeiro, você precisa decidir quantas instâncias do Steam deseja executar. O Twinverse suporta até 8 instâncias no total.

- **Tela Dividida (Splitscreen):** Você pode executar no máximo 4 instâncias por monitor.
- **Tela Cheia (Fullscreen):** Você pode executar no máximo 1 instância por monitor.

Use o seletor numérico "Número de Instâncias" para definir a quantidade desejada.

<img width="708" height="127" alt="general-layout" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/general-layout.png" />

## 2. Modo de Tela

> [!NOTE]
> Para que o auto-tiling das janelas funcione bem, é recomendado usar KDE Plasma 6.0+.
> Em outras DE, será necessário mover as janelas você mesmo, todo o resto deve funcionar bem.

Você pode escolher entre dois modos de tela:

- **Tela Cheia (Fullscreen):** Cada instância será executada em um monitor separado.
- **Tela Dividida (Splitscreen):** As instâncias serão dispostas em um único monitor, seja horizontal ou verticalmente.

<img width="708" height="204" alt="screen-settings" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/screen-settings.png" />

### Opções de Tela Dividida

Ao selecionar "Splitscreen", você pode escolher entre duas orientações:

- **Horizontal:** As instâncias são dispostas uma acima da outra.
- **Vertical:** As instâncias são dispostas lado a lado.

Posições e formatos variam de acordo com o número de instâncias.
É possível ver um preview do layout no ícone <img width="32" height="32" alt="fullscreen-square-symbolic" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/fullscreen-square-symbolic.svg" /> a esquerda em Screen Settings.

<img width="32" height="32" alt="horizontal-square-symbolic" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/horizontal-square-symbolic.svg" />
<img width="1280" height="720" alt="horizontal-game" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/horizontal-game.png" />
<img width="32" height="32" alt="vertical-square-symbolic" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/vertical-square-symbolic.svg" />
<img width="1280" height="720" alt="vertical-game" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/vertical-game.png" />

## 3. Configuração da Instância

> [!IMPORTANT]
> Para usar o Twinverse, é necessário adicionar seu usuário ao grupo `input` para permitir que o programa gerencie os dispositivos de entrada.
>
> ```bash
> sudo usermod -aG input $USER
> ```
> no Bazzite:
> ```bash
> ujust add-user-to-input-group
> ```
> **Reinicie o sistema para que as alterações entrem em vigor.**

Para cada instância, você pode configurar as seguintes opções:

- **Controle (Gamepad):** Atribuir um controle específico à instância.
- **Capturar Mouse:** Dedicar o mouse a uma única instância. Por enquanto, apenas uma instância por vez pode usar o mouse e o teclado.
- **Dispositivo de Áudio:** Selecionar um dispositivo de saída de áudio específico para a instância.
- **Taxa de Atualização (Refresh Rate):** Definir a taxa de atualização para a instância. Util se você quer travar o FPS ou usar uma taxa de atualização específica.
- **Variável de Ambiente (Environment Variables):** Definir variáveis de ambiente específicas para a instância.

<img width="595" height="409" alt="player-config" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/player-config.png" />

## 4. Iniciando uma Instância

Após configurar uma instância, clique no botão **"Start"** ao lado dela para iniciar uma instância Steam no modo desktop. Na primeira vez, o Cliente Steam será baixado e instalado automaticamente — esse processo pode levar alguns minutos.

Você deve fazer login no modo desktop. Após logar e configurar seu Cliente Steam basta encerrar a instancia.

o Botão **"Play"**, executa todas as instancias marcadas e com um check, ele vai executar todas com o gamescope e vai redimensionar cada uma.
Se você estiver usando KDE Plasma, tambem vai move-las automaticamente para dividir a tela idealmente pra seu monitor principal, ou move-las entre seu monitores caso tenha selecionado fullscreen.

Apenas instâncias que já possuem o Steam instalado podem ser iniciadas com o **"Play"**. Você pode verificar isso pelo ícone de check <img width="16" height="16" alt="check-icon" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/check-icon.svg" /> na instância. Se o ícone for um <img width="16" height="16" alt="alert-icon" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/res/icons/alert-icon.svg" />, instale o Steam clicando no botão **"Install"** daquela instância.

<img width="651" height="178" alt="instance-config" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/instance-config.png" />

## 5. Desabilitar Download Prévio de Sombreadores (Opicional)

Para meconomizar espaço em disco, desabilite o download prévio de sombreadores no Steam. Tambem recomendo fazer isso caso tenha qualquer problema com o Download de Shaders Pre-Caching.

Para fazer isso, vá em `Configurações > Downloads` e desabilita a opção `Ativar download prévio de sombreadores`.

<img width="850" height="722" alt="disable-shader-pre_caching" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/disable-shader-pre_caching.png" />

## 6. Jogar

Quando todas as suas instâncias estiverem configuradas e em execução, você pode começar a jogar! Cada instância terá seus próprios dispositivos de entrada e áudio dedicados, permitindo que você jogue com seus amigos ou familiares no mesmo computador.

Divirta-se em sua sessão de jogos!

### Atalhos de teclado:
```
Super + F       Alternar tela cheia
```
```
Super + N       Alternar filtragem por vizinho mais próximo
```
```
Super + U       Alternar e aumentar a escala FSR
```
```
Super + Y       Alternar e aumentar a escala NIS
```
```
Super + I       Aumentar a nitidez FSR em 1
```
```
Super + O       Diminuir a nitidez FSR em 1
```
```
Super + S       Tirar uma captura de tela
```
```
Super + G       Alternar captura de tela com o teclado
```

# Opcional

## Suporte a Multiplas GPUs

> [!NOTE]
> Isso deve ser adicionado diretamente no argumento dos jogos, não adicione isso ao enviroments variables.

O Twinverse suporta a execução de múltiplas Games em GPUs diferentes.

Adicione a seguinte linha aos argumentos do Steam do seu jogo:

```bash
DRI_PRIME=1!

```

Isso faz a GPU 1 ser usada no jogo. Você pode ajustar os numeros de acordo com a configuração do seu sistema.

## Diretorios Home

Você pode excluir ou gerenciar os arquivos o diretorio home de cada instância, acessando `Preferences` -> `Instances`.

<img alt="preferences-instances" src="https://raw.githubusercontent.com/mall0r/Twinverse/v1.0.0/share/screenshots/preferences-instances.png" />
