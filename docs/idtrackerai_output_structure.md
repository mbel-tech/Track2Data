# Output structure — idtrackerai 6.0.14 documentation
idtracker.ai will generate a `session_[SESSION_NAME]` folder in the same directory where the input videos are. If specified, it will be in the `--output_dir` path (see [Output](about:blank/usage.html#output)). The session folder may have the following structure:

idtracker.ai session’s output structure[#](#id2 "Link to this code")

```
session_[SESSION_NAME]
├─ accumulation
│  ├─ identifier_[cnn, contrastive].model.pt
│  └─ model_params.json
├─ crossings_detector
│  └─ crossing_detector.model.pth
├─ bounding_box_images
│  └─ bbox_images_*.h5
├─ identification_images
│  └─ id_images_*.h5
├─ preprocessing
│  ├─ background.png
│  ├─ list_of_blobs.pickle
│  ├─ list_of_fragments.json
│  ├─ list_of_global_fragments.json
│  └─ ROI_mask.png
├─ trajectories
│  ├─ trajectories_csv
│  │  ├─ areas.csv
│  │  ├─ id_probabilities.csv
│  │  ├─ trajectories.csv
│  │  └─ attributes.json
│  ├─ trajectories.h5
│  └─ trajectories.npy
├─ session.json
└─ idtrackerai.log

```


The trajectories folder has been highlighted above. It contains the most valuable data for the end user: the position of every animal in every video frame. See how to read them in [Trajectory files](#trajectory-files).

A copy of the session log `idtrackerai.log` is saved in the session folder at the end of the process (whether successful or not). This file contains information of the entire tracking process and is essential to debug and understand idtracker.ai (see [Tracking log](about:blank/usage.html#tracking-log)).

Most of the generated data is a byproduct of the tracking pipeline and is not intended for everyday use. A brief description of each folder:

*   `accumulation` — the trained identification network weights and parameters. Required by [idmatcher.ai](about:blank/idmatcherai.html#idmatcher-ai) to match identities across sessions.
    
*   `crossings_detector` — the trained individual/crossing classifier network.
    
*   `bounding_box_images` — intermediate bounding-box crops used to generate the identification images (kept only with `data_policy = "all"`).
    
*   `identification_images` — one identification image per animal per frame, stored in HDF5 format.
    
*   `preprocessing` — the [`ListOfBlobs`](about:blank/reference/generated/idtrackerai.ListOfBlobs.html#idtrackerai.ListOfBlobs "idtrackerai.ListOfBlobs"), [`ListOfFragments`](about:blank/reference/generated/idtrackerai.ListOfFragments.html#idtrackerai.ListOfFragments "idtrackerai.ListOfFragments"), and [`ListOfGlobalFragments`](about:blank/reference/generated/idtrackerai.ListOfGlobalFragments.html#idtrackerai.ListOfGlobalFragments "idtrackerai.ListOfGlobalFragments") objects (JSON and Pickle), along with the computed background image and ROI mask. Advanced users can inspect these objects for additional tracking details.
    
*   `session.json` — basic video and session properties in human-readable JSON format.
    

Trajectory files[#](#trajectory-files "Link to this heading")
-------------------------------------------------------------

The most useful files for the end user are the trajectory files, located in the folder `/trajectories`. These can be saved in multiple formats following the parameters indicated in [Output](about:blank/usage.html#output).

These files contain a dictionary-like structure with the following keys:

*   `trajectories`: Numpy array with shape (N\_frames, N\_animals, 2) with the xy coordinate for each identity and frame in the video.
    
*   `id_probabilities`: Numpy array with shape (N\_frames, N\_animals) with the probability (in \[0, 1\]) that the identity assignment is correct for each individual and frame. Higher values indicate more confident assignments; NaN indicates the animal was not detected in that frame.
    
*   `version`: idtracker.ai version which created the current file.
    
*   `height`: Video height in pixels.
    
*   `width`: Video width in pixels.
    
*   `video_paths`: input video paths.
    
*   `frames_per_second`: input video frame rate.
    
*   `body_length`: mean body length computed as the mean value of the diagonal of all individual blob’s bounding boxes.
    
*   `estimated_accuracy`: Estimated accuracy of the tracking.
    
*   `fraction_identified`: Fraction of (frame, animal) entries in the `trajectories` array that have a valid (non-NaN) position. A value of 1.0 means every animal was located in every frame.
    
*   `areas`: dictionary containing the mean, median and standard deviation of the blobs area for each individual.
    
*   `setup_points`: dictionary of the user defined setup points (from validator).
    
*   `identities_labels`: list of user defined identity labels (from validator).
    
*   `identities_groups`: list of user defined identity groups (from validator).
    
*   `length_unit`: ratio between the pixel distance and the real distance stated by the user of all pairs of points defined using the [Length Calibration](about:blank/validator.html#length-calibration) tool.
    
*   `silhouette_score`: Average silhouette score measured over a random sample of images at the end of the contrastive training.
    
*   `fragment_connectivity`: Connectivity of the fragments used in the contrastive step, computed as the average number of coexisting Fragments per Fragment, divided by the number of animals minus 1.
    

Warning

`body_length` is not a reliable measurement of the real size of the animal. Its value depends on the segmentation parameters and video conditions.

### Formats[#](#formats "Link to this heading")

The compatible formats for trajectory files and how to load them in Python:

Tip

You can convert the trajectory files of already tracked sessions to any of the compatible formats by running:

```
idtrackerai_format path/to/session_test --formats h5 npy csv csv_tidy pickle parquet

```


#### HDF5[#](#hdf5 "Link to this heading")

Hierarchical Data Formats from the [HDF Group](https://www.hdfgroup.org/solutions/hdf5/).

*   Binary format.
    
*   Cross platform, readable by many languages and softwares.
    
*   Becoming a standard in neuroscience.
    
*   Requires an extra dependency to read/write in Python, [HDF5 Python interface](https://docs.h5py.org/en/stable/).
    

```
import h5py # pip install h5py

with h5py.File("./session_test/trajectories/trajectories.h5") as file:
    trajectories = file["trajectories"][:] # load trajectories into a Numpy file
    print(file.keys()) # check all Datasets and Groups in the file
    attributes = file.attrs # check other data stored in file's attributes

```


#### Numpy[#](#numpy "Link to this heading")

Numpy’s [binary serialization](https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html) with `np.save()`.

*   Binary format.
    
*   Only readable with Python.
    
*   It uses Python’s Pickle module when saving non-Numpy data.
    
*   Not recommended for sharing since **The pickle module is not secure** (check [pickle documentation](https://docs.python.org/3/library/pickle.html)).
    
*   This format is not ideal for this type of data but is maintained for legacy support.
    

```
import numpy as np

trajectories_dict = np.load("./session_test/trajectories/trajectories.npy", allow_pickle=True).item()

```


#### Pickle[#](#pickle "Link to this heading")

Python’s [Pickle module](https://docs.python.org/3/library/pickle.html).

*   Binary format.
    
*   Only readable with Python.
    
*   Numpy uses it as the backend when saving non-Numpy data with `np.save()`.
    
*   Not recommended for sharing since **The pickle module is not secure** (check [pickle documentation](https://docs.python.org/3/library/pickle.html)).
    

```
import pickle

with open("session_test/trajectories/trajectories.pickle", "rb") as file:
    trajectories_dict = pickle.load(file)

```


#### CSV and JSON[#](#csv-and-json "Link to this heading")

*   Human-readable format.
    
*   Precision loss due to rounding.
    
*   Universal and cross-platform.
    
*   Spread over several files.
    

```
import json
import numpy as np

with open("session_test/trajectories/trajectories_csv/attributes.json", 'r') as file:
    attributes = json.load(file)

# we skip the header (first row) and the time column
trajectories = np.loadtxt("session_test/trajectories/trajectories_csv/trajectories.csv", skiprows=1, delimiter=",")
[:, 1:]
trajectories = trajectories.reshape(len(trajectories), -1, 2)

```


#### Tidy CSV[#](#tidy-csv "Link to this heading")

*   Human-readable format.
    
*   Precision loss due to rounding.
    
*   Universal and cross-platform.
    
*   Long (tidy) data layout: one row per (frame, individual) observation.
    
*   Easier to import into R, pandas, or any tool that expects tidy data.
    

The file `trajectories_tidy.csv` has the columns `frame`, `time`, `individual`, `x`, `y`, `probability`. Remaining attributes are stored in `attributes_tidy.json`.

```
import json
import numpy as np
import pandas as pd

with open("session_test/trajectories/attributes_tidy.json", "r") as file:
    attributes = json.load(file)

# DataFrame with columns: frame, time, individual, x, y, probability
df = pd.read_csv("session_test/trajectories/trajectories_tidy.csv")

# Pivot back to wide format if needed (frames × individuals)
trajectories_x = df.pivot(index="frame", columns="individual", values="x").to_numpy()
trajectories_y = df.pivot(index="frame", columns="individual", values="y").to_numpy()

# Or reconstruct the (N_frames, N_animals, 2) array without pandas:
data = np.loadtxt("session_test/trajectories/trajectories_tidy.csv", delimiter=",", skiprows=1)
n_frames = int(data[:, 0].max()) + 1
n_inds   = int(data[:, 2].max()) + 1
trajectories = data[:, 3:5].reshape(n_frames, n_inds, 2)

```


#### Parquet[#](#parquet "Link to this heading")

Apache Parquet format from the [Apache Software Foundation](https://parquet.apache.org/).

*   Columnar binary format.
    
*   Cross platform, readable by many languages and softwares.
    
*   Efficient for big data storage and retrieval.
    
*   Requires an extra dependency to read/write in Python (`pandas` and `pyarrow`).
    

```
import json
import pandas as pd
import pyarrow.parquet

table = pyarrow.parquet.read_table("session_test/trajectories/trajectories.parquet")

# DataFrame with columns: frame, time, individual, x, y, probability
df = table.to_pandas()

# JSON with metadata
attributes = json.loads(table.schema.metadata["idtrackerai_attributes"].decode("utf-8"))

```
