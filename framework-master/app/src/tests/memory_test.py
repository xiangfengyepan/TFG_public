from app.src.models.ollama_model import OllamaWrapper, MessageRoleEnum


def main():
    print("--- Testing Memory ---")
    model = OllamaWrapper()

    response = model.chat(
        [
            {
                "role": MessageRoleEnum.system,
                "content": "You are a normal person who I can talk to",
            }
        ],
    )
    OllamaWrapper.print_response(response)

    response = model.chat(
        [{"role": MessageRoleEnum.user, "content": "Hello my name is XF"}],
    )
    OllamaWrapper.print_response(response)

    response = model.chat(
        [{"role": MessageRoleEnum.user, "content": "What is my name"}],
    )
    OllamaWrapper.print_response(response)

    model = OllamaWrapper()

    response = model.chat(
        [{"role": MessageRoleEnum.user, "content": "What is my name"}],
    )
    OllamaWrapper.print_response(response)

if __name__ == "__main__":
    main()