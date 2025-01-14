# Intentional

Intentional is an open-source Python framework to build reliable LLM chatbots that actually talk and behave as you expect.

Pure LLM-based chatbots are very hard to control: when a lot of very specific instructions are pushed into their system prompt, their performance will get worse and worse the more instructions you add. These bots will work very well on small demos, but don’t scale to real use cases, where you may need the bot to follow a very specific set of workflows depending on the situation it find itself in, without improvising.

Intentional introduces a new way of prompting the LLM in a way that gives the developer full control on the conversation at scale while retaining the smooth conversational skills of the LLM.

## Getting started

First, install Intentional:

```
pip install intentional
```

Next, get a configuration file. For your first test run you should pick [this file](https://github.com/intentional-ai/intentional/blob/main/examples/example_cli_text_chat.yml), which needs no additional plugins, but you can find a few other examples [here](https://github.com/intentional-ai/intentional/tree/main/examples).

!!! note

    The example here also requires an OpenAI key. Export it as an environment variable called `OPENAI_API_KEY` before proceeding.

Assuming your configuration file is called `intentional_bot.yml`, you can now launch your bot by doing:

```
intentional intentional_bot.yml
```

The output should look like:

```
==> Chat is ready!

User:
```

Type in your message and the bot is going to respond.

### Draw the conversation

To see the graph of the conversation defined by this configuration file, run:

```
intentional intentional_bot.yml --draw
```

The graph will be saved next to your configuration file as `intentional_bot.png`.

### Running from code

If you want to run your bot from code instead of using the command line tool, this is how you can do it:

```python
import asyncio
from intentional_core import load_configuration_file

def main():
    bot = load_configuration_file("intentional_bot.yml")
    asyncio.run(bot.run())

if __name__ == "__main__":
    main()
```

You can also load an Intentional bot directly from a dictionary configuration instead of using a YAML file:

```python
import asyncio
from intentional_core import load_bot_interface_from_dict

def main():
    bot = load_bot_interface_from_dict({ ... your configuration ...})
    asyncio.run(bot.run())

if __name__ == "__main__":
    main()
```

There are other methods to load only parts of your Intentional bot, such as skipping the bot interface entirely if you want to interact with it using the Python API. To find out which methods you can use, have a look at the [API Reference](/docs/core-reference.md).

## What next?

Once you ran your first example, you should head to **[High-level Concepts](/docs/concepts.md)** to understand how to use Intentional, and then check out the specs of Intentional's **[configuration file](/docs/config-file.md)** to start building your own bots.
