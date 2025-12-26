# Guia do MultiScope

Bem-vindo ao guia do MultiScope! Este documento irá guiá-lo pelo processo de configuração e uso do aplicativo MultiScope para executar múltiplas instâncias do Steam.

[IMAGEM]

## 1. Número de Instâncias

Primeiro, você precisa decidir quantas instâncias do Steam deseja executar. O MultiScope suporta até 8 instâncias no total.

- **Tela Dividida (Splitscreen):** Você pode executar no máximo 4 instâncias por monitor.
- **Tela Cheia (Fullscreen):** Você pode executar no máximo 1 instância por monitor.

Use o seletor numérico "Número de Instâncias" para definir a quantidade desejada.

[IMAGEM]

## 2. Modo de Tela

Você pode escolher entre dois modos de tela:

- **Tela Cheia (Fullscreen):** Cada instância será executada em um monitor separado.
- **Tela Dividida (Splitscreen):** As instâncias serão dispostas em um único monitor, seja horizontal ou verticalmente.

### Opções de Tela Dividida

Ao selecionar "Splitscreen", você pode escolher entre duas orientações:

- **Horizontal:** As instâncias são dispostas lado a lado.
- **Vertical:** As instâncias são dispostas uma acima da outra.

Posições e formatos variam automaticamente de acordo com o número de instâncias.

Obs: O auto-tiling das instâncias funciona apenas com ambientes `KDE Plasma`.

[IMAGEM]

## 3. Configuração da Instância

Para cada instância, você pode configurar as seguintes opções:

- **Controle (Gamepad):** Atribuir um controle específico à instância.
- **Capturar Mouse e Teclado:** Dedicar o mouse e o teclado a uma única instância. Por enquanto, apenas uma instância por vez pode usar o mouse e o teclado.
- **Dispositivo de Áudio:** Selecionar um dispositivo de saída de áudio específico para a instância.
- **Taxa de Atualização (Refresh Rate):** Definir a taxa de atualização para a instância. Util se você quer travar o FPS ou usar uma taxa de atualização específica.
- **Variável de Ambiente (Environment Variables):** Definir variáveis de ambiente específicas para a instância.

[IMAGEM]

## 4. Iniciando uma Instância

Após configurar uma instância, clique no botão **"Start"** ao lado dela para iniciar uma instância isolada do Steam sem o gamescope. Na primeira vez, o Steam será instalado automaticamente — esse processo pode levar alguns minutos.

Cada instância pode ser iniciada individualmente pelo seu botão **"Start"**. Para executar várias de uma só vez, utilize o botão **"Jogar"** localizado na parte inferior da janela.

Apenas instâncias que já possuem o Steam instalado podem ser iniciadas com o **"Jogar"**. Você pode verificar isso pelo ícone de visto (check) na instância. Se o ícone não estiver presente, instale o Steam clicando no botão **"Start"** daquela instância. Isso permite configurar, adicionar jogos ou aplicativos de maneira rápida e direta em uma instância específica.

[IMAGEM]

## 5. Modo Big Picture do Steam (Opicional)

Para uma melhor experiência, recomenda-se ativar o "Modo Big Picture" nas configurações do Steam. Isso fornecerá uma interface amigável a controles, ideal para o MultiScope.

Para fazer isso, vá em `Configurações > Interface` e marque a caixa para `Iniciar Steam no Modo Big Picture`.

Repita esse processo para todas as instâncias que você deseja iniciar no Modo Big Picture.

[IMAGEM]

## 6. Jogar

Quando todas as suas instâncias estiverem configuradas e em execução, você pode começar a jogar! Cada instância terá seus próprios dispositivos de entrada e áudio dedicados, permitindo que você jogue com seus amigos ou familiares no mesmo computador.

Divirta-se em sua sessão de jogos!

[IMAGEM]

## 7. Aplicativos (Opcional)

Para adicionar aplicativos à sua instância, vá em `Adicionar Jogo` e clique em `Adicionar um jogo não Steam...`. Selecione o aplicativo que deseja adicionar.

### Por que fazer isso?

Isso permite que você execute aplicativos diretamente da instância, assim é possível ter uma configuração única por instância para esse aplicativo. Isso acontece pois cada instância tem seu próprio diretório `HOME` único. Eles podem ser encontrados em `~/.local/share/multiscope/home_{n}`.

Um bom exemplo de uso é o [mangojuice](https://github.com/radiolamp/mangojuice); caso queira usá-lo com configurações personalizadas você precisará executar e configurá-lo para cada instância individualmente.

[IMAGEM]
