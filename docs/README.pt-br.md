[English](../README.md) | [Português (Brasil)](./README.pt-br.md) | [Français](./README.fr.md) | [Español](./README.es.md)

# MultiScope

O **MultiScope** é uma ferramenta de código aberto para Linux que permite a criação e o gerenciamento de múltiplas instâncias do gamescope, possibilitando que vários jogadores joguem simultaneamente em um único computador.

---

## Status do Projeto

O MultiScope está atualmente em desenvolvimento ativo, mas já é totalmente funcional para usuários com **placas de vídeo AMD**. Testes em hardware **NVIDIA** ainda não foram realizados, então a compatibilidade não é garantida.

- **Compatibilidade:**
  - ✅ **AMD:** Totalmente compatível
  - ⚠️ **NVIDIA:** Requer testes
  - ⚠️ **Intel:** Requer testes

## O Problema que o MultiScope Resolve

Muitos jogadores que migram para o Linux sentem falta de ferramentas como o **Nucleus Coop**, que facilitam o multiplayer local em jogos que não o suportam nativamente. O MultiScope foi criado para preencher essa lacuna, oferecendo uma solução robusta e fácil de usar para que amigos e familiares possam jogar juntos no mesmo PC, mesmo que não tenham múltiplos computadores.

## Funcionalidades

- **Gerenciamento de Perfis:** Crie, edite e remova perfis para diferentes jogos e configurações.
- **Interface Gráfica Amigável:** Uma interface intuitiva para gerenciar perfis e instâncias de jogos.
- **Suporte a Múltiplas Telas:** Configure cada instância do jogo para rodar em uma tela específica.
- **Configurações de Áudio:** Direcione o áudio de cada instância para diferentes dispositivos de saída.
- **Suporte a Múltiplos Teclados e Mouses:** Atribua dispositivos de entrada específicos para cada jogador.

## Demonstração

*(Espaço reservado para screenshots, GIFs ou vídeos do MultiScope em ação. Para adicionar uma imagem, use a seguinte sintaxe:)*
`![Descrição da Imagem](URL_DA_IMAGEM)`

## Instalação

A forma mais simples de instalar o MultiScope é através do pacote de release, que cuidará de tudo para você.

1.  **Baixe a última release:**
    Acesse a página de [Releases](https://github.com/Mallor705/MultiScope/releases) e baixe o arquivo `MultiScope.tar.gz`.

2.  **Extraia o arquivo:**
    ```bash
    tar -xzvf MultiScope.tar.gz
    ```

3.  **Navegue para a pasta extraída:**
    (O nome da pasta pode variar dependendo da versão da release)
    ```bash
    cd MultiScope-*
    ```

4.  **Execute o script de instalação:**
    ```bash
    ./install.sh
    ```

Após a instalação, você poderá encontrar o MultiScope no menu de aplicativos do seu sistema ou executá-lo pelo terminal com o comando `multi-scope gui`. O pacote também inclui um script `uninstall.sh` para remover a aplicação.

## Como Usar

1.  **Abra o MultiScope:** Inicie a aplicação pelo menu de aplicativos ou pelo terminal.
2.  **Crie um Perfil:**
    - Clique em "Adicionar Perfil".
    - Dê um nome ao perfil (ex: "Stardew Valley - Jogador 1").
    - Configure as opções de tela, áudio e dispositivos de entrada.
    - Salve o perfil.
3.  **Inicie um Jogo:**
    - Selecione o perfil desejado.
    - Clique em "Iniciar" para abrir o jogo com as configurações definidas.

## Construindo a Partir do Código-Fonte

Se você é um desenvolvedor e deseja compilar o projeto manualmente, siga os passos abaixo:

1.  **Clone o repositório:**
    ```bash
    git clone https://github.com/Mallor705/MultiScope.git
    cd MultiScope
    ```

2.  **Para executar diretamente do código-fonte:**
    - Crie e ative um ambiente virtual:
      ```bash
      python3 -m venv .venv
      source .venv/bin/activate
      ```
    - Instale as dependências:
      ```bash
      pip install -r requirements.txt
      ```
    - Execute a aplicação:
      ```bash
      ./run.sh
      ```
    
3.  **Para compilar e instalar a partir do código-fonte:**
    ```bash
    ./build.sh
    ./install.sh
    ```

## Como Contribuir

Agradecemos o seu interesse em contribuir com o MultiScope! Se você deseja ajudar, siga estas diretrizes:

1.  **Faça um Fork do Repositório:** Crie uma cópia do projeto na sua conta do GitHub.
2.  **Crie uma Branch:** Crie uma branch para a sua nova funcionalidade ou correção (`git checkout -b minha-feature`).
3.  **Faça as Alterações:** Implemente suas melhorias ou correções.
4.  **Envie um Pull Request:** Abra um Pull Request detalhando as suas alterações.

Toda contribuição é bem-vinda, desde correções de bugs até a implementação de novas funcionalidades.

## Licença

Este projeto está licenciado sob a **Licença Pública Geral GNU v3.0 (GPL-3.0)**. Para mais detalhes, consulte o arquivo [LICENSE](LICENSE).
