# What you get:
- Arduino Nano 33 Sense Rev2 board
- main.py file
- Arduino IDE project which acts as a firmware

# What you need:
- Laptop
- Arduino Nano Sense Rev2
- Arduino IDE
- Python editor (e.g., Visual Studio)
- Python v13.x
- Claude Desktop application

# Installing instructions

- Arduino:
    1. Install Arduino IDE and open the Arduino project
    2. Connect Arduino to your computer
    3. Install libraries for your Arduino IDE: 
        - Arduino_HS300x 
        - Arduino_LPS22HB
        - Arduino_APDS9960
        - Arduino_BMI270_BMM150
        - Arduino_JSON

- Python
    1. Check which Python version you have. The exceircise require Python 3.14 minumum. Use uv or some other for making sure you have at least this version Python
    2. Install the dependencies (fastmcp, pyserial). (Depends how you run you python, e.g., uv pip install -r requirements.txt)
    3. Configure:
        - Check the Arduino port from the Aruino IDE and set in in the main.py file on the Server (e.g., PORT='/dev/cu.usbmodem11201')

- Claude
    - Install Claude Desktop, unless you have one already. You do not need paid subscript - free version is enough for this assignment!
    - Edit your Claude's config file and add your MCP server: claude_desktop_config.json. You can find this via Claude's settings -> Developer -> Edit Config. The config depends on how you run your python. Here is an example with uv:
    ```
    {
      "mcpServers": {
        "DevAIoT": {
          "command": "uv",
          "args": [
            "--directory",
            "/Users/nkm/temp/DevAIoT_2026/week3/Server",
            "run",
            "main.py"
          ]
        }
      }
    }
    ```


- Open your code editor (e.g., Visual Studio Code) and start coding!


# Assignment instructions

**Your task is to**:

1. Explore and practice: Inspect main.py and test it with Claude desktop. Practice by implementing blue LED control tool for MCP, and test it with Claude.

2. Use your creativity:
    - Design & implement *your own tool* or multiple tools
    - Design outputs for the system. Consired how this affect when the user discusses with LM.
    - "Program” on Claude: Come up with use cases for your tool(s).

3. Document & present:
    - Explain what your tool does and how it can be used with Claude
    - How should the return values and message be defined when you are communicating with LM?
    - How to combine your tool with other tools?
    - Can you actually "program" with LM




## Logs

You can observer the logs (e.g., with tail) from your Claude's log files (filename: mcp-server-DevAIoT.log)

(My logs go to /Users/nkm/Library/Logs/Claude, where yours?)




## Possible issues and solutions:

- If you get serial port issue: 1) check (from Arduino IDE) that your port is correct, 2) make sure you use pyserial - not plain serial (with uv, forcing reinstall may help: uv pip install --upgrade --force-reinstall pyserial)
