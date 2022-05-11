from trame.app import get_server
from trame.ui.vuetify import SinglePageLayout
from trame.widgets import html, vuetify

# -----------------------------------------------------------------------------
# Trame setup
# -----------------------------------------------------------------------------

server = get_server()
state, ctrl = server.state, server.controller

# -----------------------------------------------------------------------------

# Mode
initial_number = 5

# Updates
def increment():
    state.myNumber += 1


def decrement():
    state.myNumber -= 1


@state.change("myNumber")
def validate_input(myNumber, **kwargs):
    if isinstance(myNumber, str):
        try:
            state.myNumber = int(myNumber)
        except:
            state.myNumber = initial_number


# -----------------------------------------------------------------------------
# GUI
# -----------------------------------------------------------------------------
state.trame__title = "Counter"
with SinglePageLayout(server) as layout:
    layout.title.set_text("Simple Counter Demo")

    with layout.content:
        with html.Div(classes="ma-8"):
            vuetify.VBtn("Increment", click=increment)
            vuetify.VTextField(v_model=("myNumber", initial_number))
            vuetify.VBtn("Decrement", click=decrement)

if __name__ == "__main__":
    server.start()
