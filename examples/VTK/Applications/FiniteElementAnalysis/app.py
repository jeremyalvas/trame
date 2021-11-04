import io
import numpy as np
import pandas as pd

from vtkmodules.vtkCommonCore import vtkPoints, vtkIdList
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid, vtkCellArray
from vtkmodules.vtkFiltersCore import vtkThreshold
from vtkmodules.numpy_interface.dataset_adapter import numpyTovtkDataArray as np2da
from vtkmodules.util import vtkConstants

from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkDataSetMapper,
    vtkRenderer,
    vtkRenderWindow,
    vtkRenderWindowInteractor,
)

from vtkmodules.vtkInteractionStyle import vtkInteractorStyleSwitch  # noqa
import vtkmodules.vtkRenderingOpenGL2  # noqa

from trame import start, change, update_state
from trame.layouts import SinglePage
from trame.html import vuetify, vtk

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

VIEW_INTERACT = [
    {"button": 1, "action": "Rotate"},
    {"button": 2, "action": "Pan"},
    {"button": 3, "action": "Zoom", "scrollEnabled": True},
    {"button": 1, "action": "Pan", "alt": True},
    {"button": 1, "action": "Zoom", "control": True},
    {"button": 1, "action": "Pan", "shift": True},
    {"button": 1, "action": "Roll", "alt": True, "shift": True},
]

# -----------------------------------------------------------------------------
# VTK pipeline
# -----------------------------------------------------------------------------

vtk_idlist = vtkIdList()
vtk_grid = vtkUnstructuredGrid()
vtk_filter = vtkThreshold()
vtk_filter.SetInputData(vtk_grid)
field_to_keep = "my_array"

html_mesh = vtk.VtkPolyData(dataset=vtk_grid, name="mesh")
html_threshold = vtk.VtkPolyData(dataset=vtk_filter, name="threshold")

# renderer = vtkRenderer()
# renderWindow = vtkRenderWindow()
# renderWindow.AddRenderer(renderer)

# renderWindowInteractor = vtkRenderWindowInteractor()
# renderWindowInteractor.SetRenderWindow(renderWindow)
# renderWindowInteractor.GetInteractorStyle().SetCurrentStyleToTrackballCamera()

# filter_mapper = vtkDataSetMapper()
# filter_mapper.SetInputConnection(vtk_filter.GetOutputPort())
# filter_actor = vtkActor()
# filter_actor.SetMapper(filter_mapper)
# renderer.AddActor(filter_actor)

# mesh_mapper = vtkDataSetMapper()
# mesh_mapper.SetInput(vtk_grid)
# mesh_actor = vtkActor()
# mesh_actor.SetMapper(mesh_mapper)
# renderer.AddActor(mesh_actor)

@change("nodes_file", "elems_file", "field_file")
def update_grid(nodes_file, elems_file, field_file, **kwargs):
    update_state("picking_modes", [])
    if not nodes_file:
        return

    if not elems_file:
        return

    nodes_bytes = nodes_file.get("content")
    elems_bytes = elems_file.get("content")

    df_nodes = pd.read_csv(
        io.StringIO(nodes_bytes.decode("utf-8")),
        delim_whitespace=True,
        header=None,
        skiprows=1,
        names=["id", "x", "y", "z"],
    )

    df_nodes["id"] = df_nodes["id"].astype(int)
    df_nodes = df_nodes.set_index("id", drop=True)
    # fill missing ids in range as VTK uses position (index) to map cells to points
    df_nodes = df_nodes.reindex(
        np.arange(df_nodes.index.min(), df_nodes.index.max() + 1), fill_value=0
    )

    df_elems = pd.read_csv(
        io.StringIO(elems_bytes.decode("utf-8")),
        skiprows=1,
        header=None,
        delim_whitespace=True,
        engine="python",
        index_col=None,
    ).sort_values(0)
    # order: 0: eid, 1: eshape, 2+: nodes, iloc[:,0] is index
    df_elems.iloc[:, 0] = df_elems.iloc[:, 0].astype(int)

    n_nodes = df_elems.iloc[:, 1].map(
        lambda x: int("".join(i for i in x if i.isdigit()))
    )
    df_elems.insert(2, "n_nodes", n_nodes)
    # fill missing ids in range as VTK uses position (index) to map data to cells
    new_range = np.arange(df_elems.iloc[:, 0].min(), df_elems.iloc[:, 0].max() + 1)
    df_elems = df_elems.set_index(0, drop=False).reindex(new_range, fill_value=0)

    # mapping specific to Ansys Mechanical data
    vtk_shape_id_map = {
        "Tet4": vtkConstants.VTK_TETRA,
        "Tet10": vtkConstants.VTK_QUADRATIC_TETRA,
        "Hex8": vtkConstants.VTK_HEXAHEDRON,
        "Hex20": vtkConstants.VTK_QUADRATIC_HEXAHEDRON,
        "Tri6": vtkConstants.VTK_QUADRATIC_TRIANGLE,
        "Quad8": vtkConstants.VTK_QUADRATIC_QUAD,
        "Tri3": vtkConstants.VTK_TRIANGLE,
        "Quad4": vtkConstants.VTK_QUAD,
        "Wed15": vtkConstants.VTK_QUADRATIC_WEDGE,
    }
    df_elems["cell_types"] = np.nan
    df_elems.loc[df_elems.loc[:, 0] > 0, "cell_types"] = df_elems.loc[
        df_elems.loc[:, 0] > 0, 1
    ].map(
        lambda x: vtk_shape_id_map[x.strip()]
        if x.strip() in vtk_shape_id_map.keys()
        else np.nan
    )
    df_elems = df_elems.dropna(subset=["cell_types"], axis=0)

    # convert dataframes to vtk-desired format
    points = df_nodes[["x", "y", "z"]].to_numpy()
    cell_types = df_elems["cell_types"].to_numpy()
    n_nodes = df_elems.loc[:, "n_nodes"].to_numpy()
    # subtract starting node id from all grid references in cells to avoid filling from 0 to first used node (in case mesh doesnt start at 1)
    p = df_elems.iloc[:, 3:-1].to_numpy() - df_nodes.index.min()
    # if you need to, re-order nodes here-ish
    a = np.hstack((n_nodes.reshape((len(n_nodes), 1)), p))
    # convert to flat numpy array
    cells = a.ravel()
    # remove nans (due to elements with different no. of nodes)
    cells = cells[np.logical_not(np.isnan(cells))]
    cells = cells.astype(int)

    # update grid
    vtk_pts = vtkPoints()
    vtk_pts.SetData(np2da(points))
    vtk_grid.SetPoints(vtk_pts)

    vtk_cells = vtkCellArray()
    vtk_cells.SetCells(
        cell_types.shape[0], np2da(cells, array_type=vtkConstants.VTK_ID_TYPE)
    )
    vtk_grid.SetCells(
        np2da(cell_types, array_type=vtkConstants.VTK_UNSIGNED_CHAR), vtk_cells
    )

    # Add field if any
    if field_file:
        field_bytes = field_file.get("content")
        df_elem_data = pd.read_csv(
            io.StringIO(field_bytes.decode("utf-8")),
            delim_whitespace=True,
            header=None,
            skiprows=1,
            names=["id", "val"],
        )
        df_elem_data = df_elem_data.sort_values("id").set_index("id", drop=True)
        # fill missing ids in range as VTK uses position (index) to map data to cells
        df_elem_data = df_elem_data.reindex(
            np.arange(df_elems.index.min(), df_elems.index.max() + 1), fill_value=0.0
        )
        np_val = df_elem_data["val"].to_numpy()
        # assign data to grid with the name 'my_array'
        vtk_array = np2da(np_val, name=field_to_keep)
        vtk_grid.GetCellData().SetScalars(vtk_array)
        update_state("full_range", vtk_array.GetRange())
        update_state("threshold_range", vtk_array.GetRange())
        update_state("picking_modes", ["hover"])

    html_mesh.update()


@change("threshold_range")
def update_filter(threshold_range, **kwargs):
    vtk_filter.ThresholdBetween(threshold_range[0], threshold_range[1])
    html_threshold.update()


def reset():
    update_state("mesh", None)
    update_state("threshold", None)
    update_state("nodes_file", None)
    update_state("elems_file", None)
    update_state("field_file", None)


@change("pick_data")
def update_tooltip(pick_data, **kwargs):
    update_state("tooltip", "")
    update_state("tooltip_style", {"display": "none"})
    data = pick_data

    if data:
        xyx = data["worldPosition"]
        idx = vtk_grid.FindPoint(xyx)
        field = vtk_grid.GetCellData().GetArray(0)
        if idx > -1 and field:
            messages = []
            vtk_grid.GetPointCells(idx, vtk_idlist)
            for i in range(vtk_idlist.GetNumberOfIds()):
                cell_idx = vtk_idlist.GetId(i)
                value = field.GetValue(cell_idx)
                value_str = f"{value:.2f}"
                messages.append(f"Scalar: {value_str}")

            if len(messages):
                x, y, z = data["displayPosition"]
                update_state("tooltip", messages[0])
                update_state(
                    "tooltip_style",
                    {
                        "position": "absolute",
                        "left": f"{x + 10}px",
                        "bottom": f"{y + 10}px",
                        "zIndex": 10,
                        "pointerEvents": "none",
                    },
                )


# -----------------------------------------------------------------------------
# Web App setup
# -----------------------------------------------------------------------------

layout = SinglePage("FEA - Mesh viewer")
layout.logo.click = reset
layout.title.content = "Mesh Viewer"

file_style = {
    "dense": True,
    "hide_details": True,
    "style": "max-width: 200px",
    "class": "mx-2",
    "small_chips": True,
    "clearable": ("false",),
    "accept":".txt",
}

# Toolbar ----------------------------------------
with layout.toolbar:
    vuetify.VSpacer()
    vuetify.VSlider(
        thumb_size=16,
        thumb_label=True,
        label="Threshold",
        v_if="threshold",
        v_model=("threshold_range", [0, 1]),
        min=("full_range[0]",),
        max=("full_range[1]",),
        dense=True,
        hide_details=True,
        style="max-width: 400px",
    )
    vuetify.VFileInput(
        v_show="!mesh",
        prepend_icon="mdi-vector-triangle",
        v_model=("nodes_file", None),
        placeholder="Nodes",
        **file_style,
    )
    vuetify.VFileInput(
        v_show="!mesh",
        prepend_icon="mdi-dots-triangle",
        v_model=("elems_file", None),
        placeholder="Elements",
        **file_style,
    )
    vuetify.VFileInput(
        v_show="!threshold",
        prepend_icon="mdi-gradient",
        v_model=("field_file", None),
        placeholder="Field",
        **file_style,
    )
    with vuetify.VBtn(v_if="viewScene", icon=True, click="$refs.view.resetCamera()"):
        vuetify.VIcon("mdi-crop-free")

    vuetify.VProgressLinear(
        indeterminate=True,
        absolute=True,
        bottom=True,
        active=("busy",)
    )

# Content ----------------------------------------
with layout.content:
    vuetify.VContainer(
        fluid=True,
        classes="pa-0 fill-height",
        style="position: relative",
        children=[
            vtk.VtkView(
                ref="view",
                background=("[0.8, 0.8, 0.8]",),
                hover="pick_data = $event",
                picking_modes=("picking_modes", []),
                interactor_settings=("interactor_settings", VIEW_INTERACT),
                children=[
                    vtk.VtkGeometryRepresentation(
                        v_if="mesh",
                        property=("""{
                            representation: threshold ? 1 : 2,
                            color: threshold ? [0.3, 0.3, 0.3] : [1, 1, 1],
                            opacity: threshold ? 0.2 : 1
                        }""",),
                        children=[
                            vtk.VtkMesh(state=("mesh", None))
                        ],
                    ),
                    vtk.VtkGeometryRepresentation(
                        v_if="threshold",
                        color_data_range=("full_range", [0, 1]),
                        children=[
                            vtk.VtkMesh(state=("threshold", None))
                        ],
                    ),
                ],
            ),
            vuetify.VCard(
                vuetify.VCardText("<pre>{{ tooltip }}</pre>"),
                style=("tooltip_style", {"display": "none"}),
                elevation=2,
                outlined=True,
            ),
        ],
    )

layout.state = {
    # picking tooltip
    "pick_data": None,
    "tooltip": "",
}

# -----------------------------------------------------------------------------

if __name__ == "__main__":
    start(layout)
