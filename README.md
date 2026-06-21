This is a Rocket Racing Track Converter

**Fix your old Rocket Racing tracks that stopped validating without manually rebuilding them.**

If Epic's update broke your old tracks (they won't validate), this little tool fixes them. It keeps your tracks **exactly** where they
are, with the **same segments** and the **same types**
> **You do NOT need to be a coder.** You do NOT even need to understand what's
> happening. Follow the steps below because it's mostly copy paste.

---

## Do I need UEFN open to run it?

**NO** The converter runs NOT in UEFN. You use UEFN **ONLY** to

**copy** your old tracks out (`Ctrl + C`), and
**paste** the fixed ones back in (`Ctrl + V`).

---

## Steps


| Step | What you do |
|:---:|:---|
| **1** | In **UEFN**, click your old track piece or multiple pieces, then press **`Ctrl + C`** (copy). |
| **2** | **Run the converter** (see "How to run the converter?" below). |
| **3** | BReturn in **UEFN**, **delete** the old track piece(s). |
| **4** | Press **`Ctrl + V`** (paste) |

> **Try it on ONE track first!** Once you see it work, do the rest with confidence.
> **`Ctrl + Z` undoes** anything in UEFN if you happen to change your mind

---

## How to run the converter?

You need to download the source code of this repo to proceed.


There are three methods, depends on your needs.

### Easiest
Download the RR_Track_Converter **`.exe`**
Copy your tracks in UEFN.
**Launch `RR_Track_Converter.exe`.** A cmd window opens
   and says *"The NEW tracks are now on your clipboard."*
Do the steps 3 and 4 above and you done.

### With Python
If you have **Python** installed
Copy your tracks in UEFN.
Launch `convert_tracks.bat`.**
Do the steps 3 and 4 above and you done.

*(You can download python free from [python.org/downloads](https://www.python.org/downloads/) —
or just use the `.exe` above.)*

### Other methods.
In UEFN, copy your tracks, then paste them into a Notepad file and save it (e.g. `mytracks.txt`).
**Drag that file into** `RR_Track_Converter.exe` (or `rr_track_converter.py`).
It makes a new file called `mytracks_CONVERTED.txt`
Open that file, press `Ctrl + A` then `Ctrl + C`, and paste into UEFN

---

## Help

**"READ"**

---

Enjoy.
