"""
fMRI Preprocessing - HPC Submit

Submit fMRIPrep jobs to HPC with space-efficient workflow:
1. Selective upload (anat/, fmap/, func/ only - exclude dwi/)
2. Submit SLURM array job (configurable concurrent jobs)
3. Monitor progress (manual refresh button)
4. Download derivatives when complete
5. Auto-cleanup remote files

Features:
- Subject batch selection with session filtering
- SLURM resource configuration
- Job status tracking with tree view
- Error handling (continue with successful subjects)

Uses paramiko for SSH and rsync for file transfer.
"""

import streamlit as st
from pathlib import Path
import sys
from datetime import datetime
from typing import List, Dict, Optional
import json

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.hpc import (
    HPCConfig, HPCConnection, HPCWorkflowManager,
    WorkflowState, JobStatus, SubjectJobStatus
)


def _get_state_file(config: Dict) -> Path:
    """Return path to persisted workflow state JSON file."""
    bids_dir = config.get('paths', {}).get('bids_dir', '/tmp')
    state_dir = Path(bids_dir).parent / ".neuconn"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "hpc_workflow_state.json"


def _save_state_to_disk(state: WorkflowState, config: Dict):
    """Save workflow state to disk as JSON."""
    try:
        state_file = _get_state_file(config)
        with open(state_file, 'w') as f:
            json.dump(state.to_dict(), f, indent=2)
    except Exception as e:
        print(f"Warning: could not save state to disk: {e}")


def _load_state_from_disk(config: Dict) -> Optional[WorkflowState]:
    """Load workflow state from disk if it exists."""
    try:
        state_file = _get_state_file(config)
        if not state_file.exists():
            return None
        with open(state_file, 'r') as f:
            d = json.load(f)
        return WorkflowState.from_dict(d)
    except Exception as e:
        print(f"Warning: could not load state from disk: {e}")
        return None


def _clear_state_from_disk(config: Dict):
    """Delete persisted state file."""
    try:
        state_file = _get_state_file(config)
        if state_file.exists():
            state_file.unlink()
    except Exception:
        pass


def _recover_original_script(state: WorkflowState, config: Dict) -> Optional[str]:
    """Recover the original submission script from the remote project directory."""
    if state.original_script or not state.job_id or state.job_id == "reconciled":
        return state.original_script

    manager = None
    try:
        hpc_config = HPCConfig.from_config(config)
        manager = HPCWorkflowManager(
            hpc_config=hpc_config,
            local_bids=config.get('paths', {}).get('bids_dir', ''),
            local_output=config.get('paths', {}).get('fmriprep_dir', ''),
        )
        recovered_script = manager.load_submission_script()
        if recovered_script:
            state.original_script = recovered_script
        return recovered_script
    except Exception as e:
        print(f"Warning: could not recover original SLURM script: {e}")
        return None
    finally:
        if manager is not None:
            manager.close_connection()


def get_available_subjects(bids_dir: str, require_sessions: Optional[List[str]] = None) -> List[str]:
    """
    Get list of available subjects from BIDS directory.

    Args:
        bids_dir: Path to BIDS directory
        require_sessions: Only include subjects with these sessions

    Returns:
        List of subject IDs (without sub- prefix)
    """
    bids_path = Path(bids_dir)
    if not bids_path.exists():
        return []

    subjects = []
    for sub_dir in sorted(bids_path.glob("sub-*")):
        if not sub_dir.is_dir():
            continue

        sub_id = sub_dir.name.replace("sub-", "")

        # Check for required sessions
        if require_sessions:
            has_all = all(
                (sub_dir / f"ses-{ses}").exists()
                for ses in require_sessions
            )
            if not has_all:
                continue

        subjects.append(sub_id)

    return subjects


def get_remote_processed_subjects(config: Dict) -> List[str]:
    """Scan remote HPC fmriprep directory for completed subjects (have sub-*.html)."""
    try:
        from utils.hpc import HPCConfig, HPCConnection
        hpc_cfg = HPCConfig.from_config(config)
        conn = HPCConnection(hpc_cfg)
        conn.connect()
        stdout, _, code = conn.execute(
            f"ls {hpc_cfg.remote_fmriprep}/sub-*.html 2>/dev/null"
            f" | xargs -I{{}} basename {{}} .html | sed 's/sub-//'",
            timeout=30,
        )
        conn.disconnect()
        if code == 0 and stdout.strip():
            return [s.strip() for s in stdout.strip().splitlines() if s.strip()]
        return []
    except Exception:
        return []


def _reconcile_subjects(
    config: Dict,
    local_subjects: List[str],
    remote_subjects: List[str],
) -> "WorkflowState":
    """
    Build (or repair) a WorkflowState from local + remote subject lists.

    Three cases:
      A. Subject HTML exists locally             → COMPLETED (already downloaded)
      B. Subject HTML exists on HPC but not locally → COMPLETED (ready to download)
      C. Neither                                 → FAILED

    The existing state's subjects list and job_id are preserved when available so
    that subjects which haven't yet finished processing are not silently dropped.
    """
    all_subjects = sorted(set(local_subjects) | set(remote_subjects))
    existing_state = st.session_state.get('hpc_workflow_state')

    # Preserve job_id from existing state
    job_id = "reconciled"
    if existing_state and existing_state.job_id and existing_state.job_id != "reconciled":
        job_id = existing_state.job_id

    # Use the UNION of existing state subjects + all found subjects.
    # This handles multi-batch workflows where earlier batches are already
    # completed but only the latest batch is tracked in session state.
    if existing_state and existing_state.subjects:
        subjects = sorted(set(existing_state.subjects) | set(all_subjects))
    else:
        subjects = all_subjects

    # Determine step: if anything is remote-only, set to 'download' so the
    # Download & Cleanup tab is accessible.
    remote_only = set(remote_subjects) - set(local_subjects)
    current_step = 'download' if remote_only else 'completed'

    state = WorkflowState(
        subjects=subjects,
        current_step=current_step,
        job_id=job_id,
        start_time=existing_state.start_time if existing_state else datetime.now().isoformat(),
    )

    local_set = set(local_subjects)
    remote_set = set(remote_subjects)

    for idx, sub_id in enumerate(subjects):
        if sub_id in local_set:
            status = JobStatus.COMPLETED       # Case A: already downloaded
        elif sub_id in remote_set:
            status = JobStatus.COMPLETED       # Case B: on HPC, ready to download
        else:
            status = JobStatus.FAILED          # Case C: not found anywhere

        state.job_statuses.append(SubjectJobStatus(
            subject_id=sub_id,
            array_index=idx + 1,
            job_id=f"{job_id}_{idx + 1}",
            status=status,
        ))

    return state


def get_processed_subjects(fmriprep_dir: str) -> List[str]:
    """Get list of already processed subjects."""
    fmriprep_path = Path(fmriprep_dir)
    if not fmriprep_path.exists():
        return []

    subjects = []
    for sub_dir in sorted(fmriprep_path.glob("sub-*")):
        if sub_dir.is_dir():
            sub_id = sub_dir.name.replace("sub-", "")
            # Check if HTML report exists (indicates completion)
            if (fmriprep_path / f"sub-{sub_id}.html").exists():
                subjects.append(sub_id)

    return subjects


def render_subject_selection(config: Dict) -> Optional[List[str]]:
    """Render subject selection interface."""
    st.subheader("Subject Selection")

    bids_dir = config.get('paths', {}).get('bids_dir', '')
    fmriprep_dir = config.get('paths', {}).get('fmriprep_dir', '')

    if not bids_dir or not Path(bids_dir).exists():
        st.error(f"BIDS directory not found: {bids_dir}")
        st.info("Please configure BIDS directory in Settings.")
        return None

    # Session filter
    col1, col2 = st.columns(2)

    with col1:
        session_filter = st.radio(
            "Session Filter:",
            ["All subjects", "Both sessions (longitudinal)", "Session 1 only", "Session 2 only"],
            index=1,
            help="Filter subjects based on available sessions"
        )

    # Map filter to session requirements
    require_sessions = None
    if session_filter == "Both sessions (longitudinal)":
        require_sessions = ["01", "02"]
    elif session_filter == "Session 1 only":
        require_sessions = ["01"]
    elif session_filter == "Session 2 only":
        require_sessions = ["02"]

    # Get subject lists
    available = get_available_subjects(bids_dir, require_sessions)
    processed = get_processed_subjects(fmriprep_dir)

    with col2:
        st.metric("Available", len(available))
        st.metric("Already Processed", len(processed))

    # Filter options
    st.markdown("---")

    exclude_processed = st.checkbox(
        "Exclude already processed subjects",
        value=True,
        help="Uncheck to reprocess subjects"
    )

    if exclude_processed:
        selectable = [s for s in available if s not in processed]
    else:
        selectable = available

    if not selectable:
        st.warning("No subjects available for processing.")
        return None

    # Selection method
    selection_method = st.radio(
        "Selection method:",
        ["Select all", "Select incomplete", "Select specific subjects", "Select range"],
        horizontal=True,
        help="'Select incomplete' picks all subjects that have not yet been processed by fMRIPrep.",
    )

    if selection_method == "Select all":
        selected = selectable
        st.info(f"All {len(selected)} subjects selected")

    elif selection_method == "Select incomplete":
        # All available subjects that have no fMRIPrep output, regardless of the exclude_processed checkbox
        incomplete = [s for s in available if s not in processed]
        selected = incomplete
        if selected:
            st.info(
                f"**{len(selected)} incomplete** subject(s) selected (not yet processed by fMRIPrep): "
                + ", ".join(selected)
            )
        else:
            st.success("All available subjects have already been processed by fMRIPrep.")
            return None

    elif selection_method == "Select specific subjects":
        selected = st.multiselect(
            "Select subjects:",
            options=selectable,
            default=selectable[:4] if len(selectable) >= 4 else selectable,
            help="Select subjects to process"
        )

    else:  # Select range
        col1, col2 = st.columns(2)
        with col1:
            start_idx = st.number_input("Start index", min_value=0, max_value=len(selectable)-1, value=0)
        with col2:
            end_idx = st.number_input("End index", min_value=start_idx, max_value=len(selectable)-1, value=min(start_idx+3, len(selectable)-1))
        selected = selectable[start_idx:end_idx+1]
        st.info(f"Selected subjects {start_idx}-{end_idx}: {', '.join(selected)}")

    if not selected:
        st.warning("No subjects selected.")
        return None

    # Batch size
    st.markdown("---")
    batch_size = st.slider(
        "Batch size (subjects per job submission):",
        min_value=1,
        max_value=min(len(selected), 16),
        value=min(len(selected), 8),
        help="Number of subjects to process in each batch. Smaller batches reduce HPC storage usage."
    )

    # Store batch size in session state
    st.session_state.hpc_batch_size = batch_size

    # Summary
    num_batches = (len(selected) + batch_size - 1) // batch_size
    st.success(f"Ready to process {len(selected)} subjects in {num_batches} batch(es)")

    return selected


def render_configuration(config: Dict) -> Optional[Dict]:
    """Render HPC configuration interface."""
    st.subheader("HPC Configuration")

    hpc = config.get('hpc', {})
    slurm = hpc.get('slurm', {})
    fmriprep_config = config.get('fmriprep', {})

    # Check HPC is enabled
    if not hpc.get('enabled', False):
        st.error("HPC is not enabled in configuration.")
        st.info("Enable HPC in Settings -> HPC Configuration")
        return None

    # --- Initialise session_state from config on first load only ---
    if 'hpc_cfg_cpus' not in st.session_state:
        st.session_state.hpc_cfg_cpus = slurm.get('default_cpus', 8)

    if 'hpc_cfg_memory' not in st.session_state:
        raw_mem = slurm.get('default_memory', '32GB')
        try:
            st.session_state.hpc_cfg_memory = int(str(raw_mem).upper().replace('GB', '').strip())
        except ValueError:
            st.session_state.hpc_cfg_memory = 32

    if 'hpc_cfg_time_limit' not in st.session_state:
        st.session_state.hpc_cfg_time_limit = 24  # hours

    if 'hpc_cfg_max_concurrent' not in st.session_state:
        st.session_state.hpc_cfg_max_concurrent = slurm.get('max_concurrent_jobs', 4)

    if 'hpc_cfg_partition' not in st.session_state:
        st.session_state.hpc_cfg_partition = slurm.get('partition', 'shared_cpu')

    if 'hpc_cfg_output_spaces' not in st.session_state:
        st.session_state.hpc_cfg_output_spaces = fmriprep_config.get('output_spaces', [
            "MNI152NLin2009cAsym:res-2",
            "MNI152NLin6Asym:res-2",
            "T1w",
            "fsnative"
        ])

    if 'hpc_cfg_extra_flags' not in st.session_state:
        st.session_state.hpc_cfg_extra_flags = ""

    # Derive default anat_ref and checkbox values from config flags (first load only)
    default_flags = fmriprep_config.get('flags', [
        "--subject-anatomical-reference unbiased",
        "--skip-bids-validation",
        "--ignore slicetiming"
    ])
    _cfg_anat_ref = "unbiased"  # default
    for f in default_flags:
        if "--subject-anatomical-reference" in f:
            parts = f.split()
            if len(parts) >= 2:
                _cfg_anat_ref = parts[1]

    if 'hpc_cfg_anat_ref' not in st.session_state:
        st.session_state.hpc_cfg_anat_ref = _cfg_anat_ref

    if 'hpc_cfg_skip_validation' not in st.session_state:
        st.session_state.hpc_cfg_skip_validation = "--skip-bids-validation" in default_flags

    if 'hpc_cfg_ignore_slicetiming' not in st.session_state:
        st.session_state.hpc_cfg_ignore_slicetiming = "--ignore slicetiming" in default_flags

    # Connection settings (read-only display)
    with st.expander("Connection Settings", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Host", value=hpc.get('host', ''), disabled=True)
            st.text_input("User", value=hpc.get('user', ''), disabled=True)
        with col2:
            st.text_input("Remote Base", value=hpc.get('remote_paths', {}).get('base', ''), disabled=True)
            st.text_input("Singularity Image", value=hpc.get('singularity_images', {}).get('fmriprep', ''), disabled=True)

    st.markdown("---")

    # Resource configuration
    st.markdown("**SLURM Resources**")

    col1, col2, col3 = st.columns(3)

    with col1:
        cpus = st.number_input(
            "CPUs per task",
            min_value=1,
            max_value=32,
            value=st.session_state.hpc_cfg_cpus,
            key='hpc_cfg_cpus',
            help="Number of CPU cores per subject"
        )

    with col2:
        memory_gb = st.number_input(
            "Memory (GB)",
            min_value=8,
            max_value=128,
            value=st.session_state.hpc_cfg_memory,
            key='hpc_cfg_memory',
            help="Memory allocation per subject"
        )
        memory = f"{memory_gb}GB"

    with col3:
        time_hours = st.number_input(
            "Time limit (hours)",
            min_value=1,
            max_value=72,
            value=st.session_state.hpc_cfg_time_limit,
            key='hpc_cfg_time_limit',
            help="Wall clock time limit per subject"
        )
        time_limit = f"{time_hours}:00:00"

    max_concurrent = st.slider(
        "Max concurrent jobs",
        min_value=1,
        max_value=16,
        value=st.session_state.hpc_cfg_max_concurrent,
        key='hpc_cfg_max_concurrent',
        help="Maximum array tasks running simultaneously"
    )

    # Partition: dropdown populated from HPC if available, else config default
    st.markdown("**Partition**")
    available_partitions = st.session_state.get('hpc_available_partitions', [])
    config_partition = st.session_state.hpc_cfg_partition

    part_col, btn_col = st.columns([3, 1])

    with btn_col:
        fetch_btn = st.button("Fetch Partitions", help="Query HPC via SSH to get available partitions")

    if fetch_btn:
        try:
            with st.spinner("Connecting to HPC..."):
                hpc_cfg_obj = HPCConfig.from_config(config)
                conn = HPCConnection(hpc_cfg_obj)
                conn.connect()
                stdout, stderr, code = conn.execute(
                    "sinfo -h -o '%P %a %D %C' | tr -d '*'", timeout=20
                )
                conn.disconnect()

            if code == 0 and stdout.strip():
                parsed_partitions = []
                partition_info_lines = []
                for line in stdout.strip().splitlines():
                    parts_line = line.split()
                    if parts_line:
                        pname = parts_line[0].strip()
                        if pname:
                            parsed_partitions.append(pname)
                            partition_info_lines.append(line)
                if parsed_partitions:
                    st.session_state.hpc_available_partitions = parsed_partitions
                    st.session_state.hpc_partition_info_lines = partition_info_lines
                    available_partitions = parsed_partitions
                    # Keep current selection if it exists, else pick first
                    if config_partition not in available_partitions:
                        st.session_state.hpc_cfg_partition = available_partitions[0]
                        config_partition = available_partitions[0]
                    st.success(f"Found {len(parsed_partitions)} partitions")
                else:
                    st.warning("No partitions returned from sinfo")
            else:
                st.error(f"sinfo query failed: {stderr.strip() or 'unknown error'}")
        except Exception as e:
            st.error(f"Could not fetch partitions: {e}")

    with part_col:
        if available_partitions:
            # Ensure current value is in the list
            if config_partition not in available_partitions:
                options = [config_partition] + available_partitions
            else:
                options = available_partitions
            partition_idx = options.index(config_partition) if config_partition in options else 0
            partition = st.selectbox(
                "Partition",
                options=options,
                index=partition_idx,
                key='hpc_cfg_partition',
                help="SLURM partition name"
            )
            # Show node info caption if available
            info_lines = st.session_state.get('hpc_partition_info_lines', [])
            if info_lines:
                st.caption("Partition · Avail · Nodes · CPUs(A/I/O/T)\n" +
                           "\n".join(info_lines))
        else:
            partition = st.selectbox(
                "Partition",
                options=[config_partition],
                index=0,
                key='hpc_cfg_partition',
                help="SLURM partition name. Click 'Fetch Partitions' to see all available partitions."
            )
            st.caption("Click **Fetch Partitions** to query available partitions from the cluster.")

    st.markdown("---")

    # fMRIPrep settings
    st.markdown("**fMRIPrep Settings**")

    output_spaces = st.multiselect(
        "Output spaces",
        options=[
            "MNI152NLin2009cAsym:res-2",
            "MNI152NLin6Asym:res-2",
            "MNI152NLin2009cAsym:res-1",
            "T1w",
            "fsnative"
        ],
        default=st.session_state.hpc_cfg_output_spaces,
        key='hpc_cfg_output_spaces',
        help="Standard spaces for output registration"
    )

    # Anatomical reference method (replaces --longitudinal in fMRIPrep 25+)
    anat_ref_options = ["unbiased", "first-lex", "sessionwise"]
    current_anat_ref = st.session_state.hpc_cfg_anat_ref
    if current_anat_ref not in anat_ref_options:
        current_anat_ref = "unbiased"  # default

    anat_ref = st.selectbox(
        "Anatomical reference method",
        anat_ref_options,
        index=anat_ref_options.index(current_anat_ref),
        key='hpc_cfg_anat_ref',
        help="unbiased = cross-session template (previously --longitudinal); first-lex = use first session; sessionwise = process each session independently"
    )

    skip_validation = st.checkbox(
        "Skip BIDS validation",
        value=st.session_state.hpc_cfg_skip_validation,
        key='hpc_cfg_skip_validation',
        help="Skip BIDS dataset validation"
    )

    ignore_slicetiming = st.checkbox(
        "Ignore slice timing",
        value=st.session_state.hpc_cfg_ignore_slicetiming,
        key='hpc_cfg_ignore_slicetiming',
        help="Skip slice timing correction"
    )

    # Build flags list from UI selections
    flags = [f"--subject-anatomical-reference {anat_ref}"]
    if skip_validation:
        flags.append("--skip-bids-validation")
    if ignore_slicetiming:
        flags.append("--ignore slicetiming")

    # Extra flags
    extra_flags_str = st.text_input(
        "Additional flags (optional)",
        value=st.session_state.hpc_cfg_extra_flags,
        key='hpc_cfg_extra_flags',
        help="Space-separated additional fMRIPrep flags"
    )
    if extra_flags_str.strip():
        flags.extend(extra_flags_str.strip().split())

    # Return configuration
    return {
        'cpus': cpus,
        'memory': memory,
        'time_limit': time_limit,
        'max_concurrent': max_concurrent,
        'partition': partition,
        'output_spaces': output_spaces,
        'flags': flags
    }


def render_script_preview(config: Dict, subjects: List[str], slurm_config: Dict):
    """Render SLURM script preview."""
    st.subheader("SLURM Script Preview")

    try:
        hpc_config = HPCConfig.from_config(config)

        # Override with user settings
        hpc_config.partition = slurm_config['partition']
        hpc_config.cpus = slurm_config['cpus']
        hpc_config.memory = slurm_config['memory']
        hpc_config.time_limit = slurm_config['time_limit']
        hpc_config.max_concurrent = slurm_config['max_concurrent']

        manager = HPCWorkflowManager(
            hpc_config=hpc_config,
            local_bids=config.get('paths', {}).get('bids_dir', ''),
            local_output=config.get('paths', {}).get('fmriprep_dir', ''),
            fmriprep_config={
                'output_spaces': slurm_config['output_spaces'],
                'flags': slurm_config['flags']
            }
        )

        script = manager.generate_slurm_script(
            subjects=subjects,
            cpus=slurm_config['cpus'],
            memory=slurm_config['memory'],
            time_limit=slurm_config['time_limit'],
            max_concurrent=slurm_config['max_concurrent']
        )

        st.code(script, language="bash")

        # Store script in session state
        st.session_state.hpc_slurm_script = script

    except Exception as e:
        st.error(f"Error generating script: {e}")
        import traceback
        st.code(traceback.format_exc())


def render_upload_submit(config: Dict, subjects: List[str], slurm_config: Dict):
    """Render upload and submit interface."""
    st.subheader("Upload & Submit")

    # Initialize workflow state
    if 'hpc_workflow_state' not in st.session_state:
        st.session_state.hpc_workflow_state = None

    state = st.session_state.hpc_workflow_state

    # Status display
    if state:
        st.info(f"Current step: **{state.current_step}** | Job ID: {state.job_id or 'N/A'}")

        if state.errors:
            st.error(f"Errors: {'; '.join(state.errors)}")

    # Upload section
    st.markdown("### 1. Upload BIDS Data")

    hpc = config.get('hpc', {})
    modalities = hpc.get('transfer', {}).get('modalities', ['anat', 'fmap', 'func'])
    remote_paths = hpc.get('remote_paths', {})
    base = remote_paths.get('base', '')
    remote_bids = remote_paths.get('bids', base + '/bids').replace('${base}', base)
    remote_fmriprep = remote_paths.get('fmriprep', base + '/fmriprep').replace('${base}', base)
    remote_work = remote_paths.get('work', base + '/work').replace('${base}', base)
    host = hpc.get('host', '')
    user = hpc.get('user', '')

    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.markdown("**📤 Uploading:**")
        st.markdown(f"- Modalities: `{'`, `'.join(modalities)}`")
        st.markdown(f"- {len(subjects)} subjects")
        st.markdown(f"- Source: `{config.get('paths', {}).get('bids_dir', '')}`")
    with col_info2:
        st.markdown("**🖥️ Destination (HPC):**")
        st.markdown(f"- Host: `{user}@{host}`")
        st.markdown(f"- BIDS: `{remote_bids}`")
        st.markdown(f"- Output: `{remote_fmriprep}`")
        st.markdown(f"- Work: `{remote_work}`")

    st.markdown("---")

    # Show failed-subjects banner with Retry / Proceed buttons
    _retry_subjects = None
    if state and getattr(state, 'failed_subjects', []):
        failed_list = state.failed_subjects
        st.warning(
            f"⚠️ {len(failed_list)} subject(s) failed last upload: "
            f"`{'`, `'.join(failed_list)}`"
        )
        col_retry, col_proceed = st.columns(2)

        with col_retry:
            if st.button(f"🔁 Retry {len(failed_list)} Failed Subject(s)"):
                _retry_subjects = failed_list[:]
                state.failed_subjects = []
                state.errors = [e for e in state.errors
                                if not e.startswith("Upload failed for:")]
                st.session_state.hpc_workflow_state = state
                _save_state_to_disk(state, config)

        with col_proceed:
            if st.button("➡️ Proceed with Successful Only"):
                state.failed_subjects = []
                state.current_step = 'submit'
                st.session_state.hpc_workflow_state = state
                _save_state_to_disk(state, config)
                st.rerun()

    col1, col2 = st.columns(2)

    with col1:
        upload_btn = st.button(
            "Start Upload",
            type="primary",
            disabled=(state is not None and state.current_step not in ['upload', 'completed']),
            help="Upload BIDS data to HPC"
        )

    with col2:
        if state and state.upload_progress:
            completed = sum(1 for s in state.upload_progress.values() if s == 'Complete')
            total = max(len(state.upload_progress), len(subjects))
            st.progress(min(completed / total, 1.0), text=f"Uploaded: {completed}/{total}")

    # Determine which subjects to upload (retry subset or full list)
    subjects_for_upload = _retry_subjects if _retry_subjects else subjects

    if upload_btn or _retry_subjects:
        # Initialize state
        state = WorkflowState(
            subjects=subjects_for_upload,
            current_step='upload',
            start_time=datetime.now().isoformat()
        )
        st.session_state.hpc_workflow_state = state
        _save_state_to_disk(state, config)

        # Create manager
        try:
            hpc_config = HPCConfig.from_config(config)
            manager = HPCWorkflowManager(
                hpc_config=hpc_config,
                local_bids=config.get('paths', {}).get('bids_dir', ''),
                local_output=config.get('paths', {}).get('fmriprep_dir', ''),
                fmriprep_config={
                    'output_spaces': slurm_config['output_spaces'],
                    'flags': slurm_config['flags']
                }
            )

            # Upload with progress
            progress_placeholder = st.empty()
            status_placeholder = st.empty()

            def upload_callback(sub_id, status, progress):
                state.upload_progress[sub_id] = status
                progress_placeholder.progress(progress, text=f"Uploading sub-{sub_id}: {status}")
                status_placeholder.write(f"Progress: {status}")

            with st.spinner(f"Uploading {len(subjects_for_upload)} subject(s)..."):
                results = manager.upload_batch_selective(
                    subjects_for_upload, progress_callback=upload_callback
                )

            # Update state based on results
            successful = [s for s, ok in results.items() if ok]
            failed = [s for s, ok in results.items() if not ok]

            state.failed_subjects = failed

            if failed:
                state.errors.append(f"Upload failed for: {', '.join(failed)}")

            if successful and not failed:
                # All succeeded → advance to submit
                state.subjects = successful
                state.current_step = 'submit'
                st.success(f"✅ Upload complete: {len(successful)}/{len(subjects_for_upload)} subjects")
            elif successful and failed:
                # Partial failure → stay on upload so Retry/Proceed buttons appear
                state.subjects = successful
                state.current_step = 'upload'
                st.warning(
                    f"⚠️ Partial upload: **{len(successful)} succeeded**, "
                    f"**{len(failed)} failed** (`{'`, `'.join(failed)}`). "
                    f"Use Retry or Proceed buttons above."
                )
            else:
                # All failed → stay on upload
                state.current_step = 'upload'
                st.error("❌ All uploads failed! Check HPC connection and retry.")

            st.session_state.hpc_workflow_state = state
            _save_state_to_disk(state, config)
            st.rerun()

        except Exception as e:
            st.error(f"Upload error: {e}")
            import traceback
            st.code(traceback.format_exc())

    # Submit section
    st.markdown("---")
    st.markdown("### 2. Submit SLURM Job")

    can_submit = state is not None and state.current_step == 'submit'

    submit_btn = st.button(
        "Submit Job",
        type="primary" if can_submit else "secondary",
        disabled=not can_submit,
        help="Submit fMRIPrep job to HPC queue"
    )

    if submit_btn and can_submit:
        try:
            hpc_config = HPCConfig.from_config(config)
            manager = HPCWorkflowManager(
                hpc_config=hpc_config,
                local_bids=config.get('paths', {}).get('bids_dir', ''),
                local_output=config.get('paths', {}).get('fmriprep_dir', ''),
                fmriprep_config={
                    'output_spaces': slurm_config['output_spaces'],
                    'flags': slurm_config['flags']
                }
            )

            script = st.session_state.get('hpc_slurm_script')

            with st.spinner("Submitting job..."):
                job_id = manager.submit_job(
                    state.subjects,
                    script_content=script,
                    cpus=slurm_config['cpus'],
                    memory=slurm_config['memory'],
                    time_limit=slurm_config['time_limit'],
                    max_concurrent=slurm_config['max_concurrent']
                )

            state.job_id = job_id
            state.current_step = 'monitor'
            # Store the SLURM script so restarts can reuse it
            if script:
                state.original_script = script
            else:
                # Script was auto-generated — regenerate and store
                state.original_script = manager.generate_slurm_script(
                    state.subjects,
                    cpus=slurm_config['cpus'],
                    memory=slurm_config['memory'],
                    time_limit=slurm_config['time_limit'],
                    max_concurrent=slurm_config['max_concurrent'],
                )
            st.session_state.hpc_workflow_state = state
            _save_state_to_disk(state, config)

            st.success(f"Job submitted! ID: {job_id}")
            st.rerun()

        except Exception as e:
            st.error(f"Submission error: {e}")
            import traceback
            st.code(traceback.format_exc())


def render_cluster_status(config: Dict):
    """Show cluster resource usage and queue status."""
    st.subheader("🖥️ Cluster Status")

    if st.button("🔄 Refresh Cluster Status", key="refresh_cluster"):
        pass  # Just rerun below

    try:
        from utils.hpc import HPCConfig, HPCConnection
        hpc_cfg = HPCConfig.from_config(config)
        conn = HPCConnection(hpc_cfg)
        conn.connect()

        # Run all queries in one SSH session
        commands = {
            "queue_all":   "squeue -o '%.10i %.9P %.20j %.8u %.8T %.10M %.6D %R' 2>/dev/null | head -50",
            "queue_mine":  f"squeue -u {hpc_cfg.user} -o '%.10i %.9P %.20j %.8T %.10M %.6D %R' 2>/dev/null",
            "node_info":   "sinfo -o '%.12P %.5a %.10l %.6D %.6t %.8c %.8m %N' 2>/dev/null",
            "my_usage":    f"sacct -u {hpc_cfg.user} --starttime=$(date -d '7 days ago' +%Y-%m-%d) -o JobID,JobName,Partition,State,CPUTime,MaxRSS,Start,End --noheader 2>/dev/null | tail -20",
            "disk_space":  f"df -h {hpc_cfg.remote_base or '/home/' + hpc_cfg.user} 2>/dev/null | tail -1",
            "home_quota":  f"quota -s 2>/dev/null | grep -v 'Filesystem\|Disk quotas\|^$' | head -3",
        }

        results = {}
        for key, cmd in commands.items():
            stdout, stderr, code = conn.execute(cmd, timeout=30)
            results[key] = stdout.strip() if code == 0 else f"(error: {stderr.strip()})"

        conn.disconnect()

        # --- Queue overview ---
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**📋 All Jobs in Queue**")
            if results["queue_all"]:
                lines = results["queue_all"].split('\n')
                running = sum(1 for l in lines if 'RUNNING' in l)
                pending = sum(1 for l in lines if 'PENDING' in l)
                total   = len(lines) - 1  # subtract header

                m1, m2, m3 = st.columns(3)
                m1.metric("Total Jobs", total)
                m2.metric("🟢 Running", running)
                m3.metric("🟡 Pending", pending)
                st.code(results["queue_all"], language=None)
            else:
                st.success("✅ Queue is empty — cluster is free!")

        with col2:
            st.markdown(f"**👤 Your Jobs ({hpc_cfg.user})**")
            if results["queue_mine"]:
                lines = results["queue_mine"].split('\n')
                my_running = sum(1 for l in lines if 'RUNNING' in l)
                my_pending = sum(1 for l in lines if 'PENDING' in l)
                my_total = len([l for l in lines if l.strip() and not l.startswith('JOBID')])

                m1, m2, m3 = st.columns(3)
                m1.metric("Your Jobs", my_total)
                m2.metric("🟢 Running", my_running)
                m3.metric("🟡 Pending", my_pending)
                st.code(results["queue_mine"], language=None)
            else:
                st.success("✅ No active jobs")

        # --- Node availability ---
        st.markdown("**🔧 Node Availability**")
        if results["node_info"]:
            lines = [l for l in results["node_info"].split('\n') if l.strip()]
            idle_nodes = sum(1 for l in lines if ' idle' in l or ' mix' in l)
            st.caption(f"Partitions with idle/mixed nodes: {idle_nodes}")
            st.code(results["node_info"], language=None)

            # Populate partition dropdown from node_info (skip header line)
            # sinfo -o '%.12P %.5a %.10l %.6D %.6t %.8c %.8m %N' has a header row
            data_lines = [l for l in lines if not l.strip().startswith('PARTITION')]
            parsed_partitions = []
            partition_info_lines = []
            for line in data_lines:
                parts_line = line.split()
                if parts_line:
                    pname = parts_line[0].strip().rstrip('*')
                    if pname:
                        parsed_partitions.append(pname)
                        partition_info_lines.append(line)
            if parsed_partitions:
                st.session_state.hpc_available_partitions = parsed_partitions
                st.session_state.hpc_partition_info_lines = partition_info_lines
                st.caption(f"✅ Populated {len(parsed_partitions)} partitions for the Configuration tab.")

        # --- Disk space ---
        st.markdown("**💾 Disk Space**")

        def render_df_metrics(label: str, df_line: str):
            """Parse df -h output line and show as metrics."""
            st.caption(f"📁 {label}")
            if not df_line or not df_line.strip():
                st.caption("_(not available)_")
                return
            # df -h output: Filesystem  Size  Used  Avail  Use%  Mountpoint
            parts = df_line.split()
            if len(parts) >= 5:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total", parts[1])
                c2.metric("Used", parts[2])
                c3.metric("Available", parts[3])
                c4.metric("Use%", parts[4])
            else:
                st.code(df_line, language=None)

        col1, col2 = st.columns(2)
        with col1:
            render_df_metrics(f"Project dir ({hpc_cfg.remote_base})", results["disk_space"])
        with col2:
            st.caption("📊 User Quota")
            quota_raw = results.get("home_quota", "")
            if quota_raw and quota_raw.strip():
                # quota -s output spans two lines:
                #   Line 1: filesystem path (e.g. 172.18.32.51:/mnt/...)
                #   Line 2: <spaces> space quota limit grace files quota limit grace
                # Find the values line: starts with whitespace and has size values
                lines = quota_raw.strip().splitlines()
                parsed = False
                for line in lines:
                    # Values line starts with whitespace (indented)
                    if line.startswith(' ') or line.startswith('\t'):
                        parts = line.split()
                        if len(parts) >= 3:
                            used  = parts[0]  # space used
                            quota = parts[1]  # quota
                            limit = parts[2]  # limit
                            # Calculate use%
                            try:
                                def to_gb(s):
                                    s = s.strip()
                                    val = float(s[:-1])
                                    unit = s[-1].upper()
                                    return val * {'G': 1, 'M': 1/1024, 'K': 1/1024/1024, 'T': 1024}.get(unit, 1)
                                pct = round(100 * to_gb(used) / to_gb(quota), 1)
                                use_pct = f"{pct}%"
                            except Exception:
                                use_pct = "N/A"
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Used", used)
                            c2.metric("Quota", quota)
                            c3.metric("Limit", limit)
                            c4.metric("Use%", use_pct)
                            parsed = True
                            break
                if not parsed:
                    st.code(quota_raw, language=None)
            else:
                st.caption("_(quota not available on this system)_")

        # --- Recent jobs ---
        with st.expander("📊 Your Recent Jobs (last 7 days)"):
            if results["my_usage"]:
                st.code(results["my_usage"], language=None)
            else:
                st.info("No recent jobs found")

    except Exception as e:
        st.error(f"Could not connect to HPC: {e}")
        st.caption("Check HPC settings and SSH connection")


def render_monitor(config: Dict):
    """Render job monitoring interface."""
    st.subheader("Monitor Jobs")

    state = st.session_state.get('hpc_workflow_state')

    # ---- Recovery section: shown when no state or job_id is None/reconciled ----
    if not state or not state.job_id:
        fmriprep_dir = config.get('paths', {}).get('fmriprep_dir', '')
        local_found = get_processed_subjects(fmriprep_dir)

        if local_found:
            st.warning(
                f"⚠️ No active job state found, but **{len(local_found)} subject(s)** appear "
                f"already processed locally (`{fmriprep_dir}`). "
                f"Use **🔄 Reconcile** below to restore tracking."
            )
        else:
            st.info("No active job to monitor. Submit a job first.")

        st.caption(f"🔍 Scanning: `{fmriprep_dir}` → found {len(local_found)} processed subjects: {local_found}")

        with st.expander("🔄 Reconcile from Files", expanded=True):
            col_a, col_b = st.columns(2)

            with col_a:
                if st.button(
                    "🔍 Scan Local Only",
                    key="reconcile_empty_local",
                    help="Mark subjects with local HTML as COMPLETED",
                    disabled=not bool(local_found),
                ):
                    state_new = _reconcile_subjects(config, local_found, [])
                    st.session_state.hpc_workflow_state = state_new
                    _save_state_to_disk(state_new, config)
                    st.success(
                        f"✅ {len(local_found)} subject(s) marked COMPLETED from local files. "
                        f"State saved to disk."
                    )
                    st.rerun()

            with col_b:
                if st.button(
                    "🌐 Scan Local + Remote HPC",
                    key="reconcile_empty_remote",
                    help="Also SSH to HPC to find subjects ready for download",
                ):
                    with st.spinner("Connecting to HPC..."):
                        remote_found = get_remote_processed_subjects(config)
                    remote_only = [s for s in remote_found if s not in local_found]
                    st.caption(
                        f"HPC fmriprep: **{len(remote_found)} subjects** found on HPC "
                        f"({len(remote_only)} not yet downloaded)"
                    )
                    state_new = _reconcile_subjects(config, local_found, remote_found)
                    st.session_state.hpc_workflow_state = state_new
                    _save_state_to_disk(state_new, config)
                    if remote_only:
                        st.warning(
                            f"⚠️ {len(remote_only)} subject(s) ready to download from HPC: {remote_only}"
                        )
                        st.info("Go to **Download & Cleanup** tab to download them.")
                    elif local_found:
                        st.success(f"✅ All {len(local_found)} subject(s) already local. State updated.")
                    else:
                        st.error("No processed subjects found locally or on HPC.")
                    st.rerun()

        return  # nothing more to render until reconciled (or a real job is submitted)

    # Determine if this is a real SLURM job or a reconciled (local-only) state
    is_real_job = bool(state.job_id) and state.job_id != "reconciled"

    if is_real_job:
        st.info(f"Job ID: **{state.job_id}** | Subjects: {len(state.subjects)}")
    else:
        st.info(f"Reconciled state · {len(state.subjects)} subject(s) tracked locally · no active SLURM job")

    # Refresh button
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        refresh_btn = st.button(
            "Refresh Status",
            type="primary",
            disabled=not is_real_job,
            help="Check SLURM job status (disabled for reconciled/local-only state)" if not is_real_job else "",
        )

    with col2:
        cancel_btn = st.button(
            "Cancel Job",
            type="secondary",
            disabled=not is_real_job,
        )

    with col3:
        if st.button("🗑️ Clear Job State", key="clear_job_state"):
            del st.session_state.hpc_workflow_state
            _clear_state_from_disk(config)
            st.success("Job state cleared")
            st.rerun()

    # --- Reconcile section (always visible for post-cleanup or false-FAILED corrections) ---
    fmriprep_dir = config.get('paths', {}).get('fmriprep_dir', '')
    local_found = get_processed_subjects(fmriprep_dir)

    with st.expander("🔄 Reconcile from Files", expanded=False):
        st.caption(
            f"🔍 Scanning: `{fmriprep_dir}` → **{len(local_found)} subject(s)** found locally: {local_found}"
        )

        col_a, col_b = st.columns(2)

        with col_a:
            if st.button(
                "🔍 Scan Local Only",
                key="reconcile_always_local",
                help="Mark subjects with local HTML as COMPLETED",
            ):
                state_new = _reconcile_subjects(config, local_found, [])
                st.session_state.hpc_workflow_state = state_new
                _save_state_to_disk(state_new, config)
                st.success(f"✅ {len(local_found)} subject(s) marked COMPLETED from local files.")
                st.rerun()

        with col_b:
            if st.button(
                "🌐 Scan Local + Remote HPC",
                key="reconcile_always_remote",
                help="Also SSH to HPC to find subjects ready for download",
            ):
                with st.spinner("Connecting to HPC..."):
                    remote_found = get_remote_processed_subjects(config)
                remote_only = [s for s in remote_found if s not in local_found]
                st.caption(
                    f"HPC fmriprep: **{len(remote_found)} subjects** found on HPC "
                    f"({len(remote_only)} not yet downloaded)"
                )
                state_new = _reconcile_subjects(config, local_found, remote_found)
                st.session_state.hpc_workflow_state = state_new
                _save_state_to_disk(state_new, config)
                if remote_only:
                    st.warning(
                        f"⚠️ {len(remote_only)} subject(s) ready to download from HPC: {remote_only}"
                    )
                    st.info("Go to **Download & Cleanup** tab to download them.")
                else:
                    st.success(f"✅ All {len(local_found)} subject(s) already local. State updated.")
                st.rerun()

    if refresh_btn:
        try:
            hpc_config = HPCConfig.from_config(config)
            manager = HPCWorkflowManager(
                hpc_config=hpc_config,
                local_bids=config.get('paths', {}).get('bids_dir', ''),
                local_output=config.get('paths', {}).get('fmriprep_dir', '')
            )

            local_fmriprep = config.get('paths', {}).get('fmriprep_dir', '') or None
            with st.spinner("Checking job status..."):
                statuses = manager.check_all_job_statuses(
                    state,
                    local_fmriprep_dir=local_fmriprep,
                )

            state.job_statuses = statuses
            st.session_state.hpc_workflow_state = state
            _save_state_to_disk(state, config)

            # Check if all tasks are in a terminal state (completed or failed)
            if manager.is_job_complete(statuses):
                completed_count = sum(1 for s in statuses if s.status == JobStatus.COMPLETED)
                failed_count = sum(1 for s in statuses if s.status in (
                    JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMEOUT, JobStatus.NODE_FAIL
                ))
                state.current_step = 'download'
                st.session_state.hpc_workflow_state = state
                _save_state_to_disk(state, config)
                if failed_count > 0:
                    st.warning(
                        f"⚠️ Jobs finished: **{completed_count} completed**, **{failed_count} failed**. "
                        f"You can still download results for completed subjects."
                    )
                else:
                    st.success(f"✅ All {completed_count} jobs completed! Ready to download.")

        except Exception as e:
            st.error(f"Error checking status: {e}")

    if cancel_btn:
        try:
            hpc_config = HPCConfig.from_config(config)
            conn = HPCConnection(hpc_config)
            conn.connect()
            conn.execute(f"scancel {state.job_id}")
            conn.disconnect()
            st.warning(f"Job {state.job_id} cancelled.")
        except Exception as e:
            st.error(f"Error cancelling job: {e}")

    # Status display
    st.markdown("---")

    if state.job_statuses:
        # Summary metrics
        status_counts = {}
        for s in state.job_statuses:
            status_counts[s.status.value] = status_counts.get(s.status.value, 0) + 1

        cols = st.columns(len(status_counts) + 1)
        cols[0].metric("Total", len(state.job_statuses))

        for idx, (status, count) in enumerate(status_counts.items()):
            cols[idx + 1].metric(status, count)

        # Summary counts
        completed = sum(1 for s in state.job_statuses if s.status == JobStatus.COMPLETED)
        failed    = sum(1 for s in state.job_statuses if s.status in (
            JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMEOUT, JobStatus.NODE_FAIL))
        running   = sum(1 for s in state.job_statuses if s.status == JobStatus.RUNNING)
        pending   = sum(1 for s in state.job_statuses if s.status == JobStatus.PENDING)
        total     = len(state.job_statuses)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total",     total)
        c2.metric("✅ Done",   completed)
        c3.metric("❌ Failed", failed)
        c4.metric("🔄 Running", running)
        c5.metric("⏳ Pending", pending)

        # Progress bar (only completed counts as done; failed = known)
        progress = completed / total if total > 0 else 0
        bar_text = f"{completed}/{total} completed"
        if failed:
            bar_text += f" · {failed} failed"
        if running:
            bar_text += f" · {running} running"
        st.progress(progress, text=bar_text)

        # Prompt to download if all terminal
        if running == 0 and pending == 0 and completed > 0:
            st.info(f"🎉 All tasks finished. **{completed}** ready to download"
                    + (f", **{failed}** failed (will be skipped)." if failed else "."))

        # Status table
        st.markdown("### Subject Status")

        table_data = []
        for s in state.job_statuses:
            status_emoji = {
                JobStatus.PENDING:    "⏳",
                JobStatus.RUNNING:    "🔄",
                JobStatus.COMPLETING: "🔄",
                JobStatus.COMPLETED:  "✅",
                JobStatus.FAILED:     "❌",
                JobStatus.CANCELLED:  "🚫",
                JobStatus.TIMEOUT:    "⏰",
                JobStatus.NODE_FAIL:  "💥",
                JobStatus.UNKNOWN:    "❓"
            }.get(s.status, "❓")

            table_data.append({
                "Subject":  f"sub-{s.subject_id}",
                "Status":   f"{status_emoji} {s.status.value}",
                "Node":     s.node or "-",
                "Elapsed":  s.elapsed_time or "-",
                "Job ID":   s.job_id
            })

        st.dataframe(table_data, width="stretch")

        # ── Kill & Restart Controls ──────────────────────────────────
        _render_kill_restart(state, config)

    else:
        st.info("Click 'Refresh Status' to check job progress.")


# Statuses eligible for restart
_RESTARTABLE_STATUSES = {
    JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMEOUT, JobStatus.NODE_FAIL, JobStatus.UNKNOWN,
}

_KILLABLE_STATUSES = {
    JobStatus.RUNNING, JobStatus.PENDING, JobStatus.COMPLETING, JobStatus.UNKNOWN,
}


def _render_kill_restart(state: WorkflowState, config: Dict):
    """Render kill & restart controls inside the monitor tab."""
    is_real_job = bool(state.job_id) and state.job_id != "reconciled"

    killable = [s for s in state.job_statuses if s.status in _KILLABLE_STATUSES]
    restartable = [s for s in state.job_statuses if s.status in _RESTARTABLE_STATUSES]

    if not killable and not restartable:
        return  # Nothing actionable — don't clutter the UI

    with st.expander("⚡ Kill & Restart Individual Tasks", expanded=False):
        kill_col, restart_col = st.columns(2)

        # ── LEFT: Kill stuck tasks ───────────────────────────────
        with kill_col:
            st.markdown("**Kill Stuck Tasks**")
            st.caption("For tasks still active in SLURM or stuck in an indeterminate state.")

            if not killable:
                st.info("No actionable tasks to kill.")
            elif not is_real_job:
                st.info("Cannot kill tasks for reconciled state.")
            else:
                kill_options = {
                    f"sub-{s.subject_id} ({s.status.value})": s.subject_id
                    for s in killable
                }
                to_kill = st.multiselect(
                    "Select subjects to kill",
                    options=list(kill_options.keys()),
                    key="kill_subject_select",
                )
                kill_ids = [kill_options[label] for label in to_kill]

                if st.button("Kill Selected", disabled=not to_kill, type="secondary", key="kill_btn"):
                    try:
                        hpc_config = HPCConfig.from_config(config)
                        manager = HPCWorkflowManager(
                            hpc_config=hpc_config,
                            local_bids=config.get('paths', {}).get('bids_dir', ''),
                            local_output=config.get('paths', {}).get('fmriprep_dir', ''),
                        )
                        targets = [s for s in killable if s.subject_id in kill_ids]
                        with st.spinner("Sending scancel..."):
                            results = manager.cancel_tasks(state.job_id, targets)

                        failed_kills = [sid for sid, ok in results.items() if not ok]
                        if failed_kills:
                            st.warning(
                                f"scancel failed for: {', '.join(failed_kills)}. "
                                "They may have already finished — refresh to confirm."
                            )
                        else:
                            st.success(
                                f"Sent scancel for {len(results)} task(s). "
                                "Click **Refresh Status** to see updated state."
                            )
                    except Exception as e:
                        st.error(f"Error killing tasks: {e}")

        # ── RIGHT: Restart failed/cancelled tasks ────────────────
        with restart_col:
            st.markdown("**Restart Failed / Cancelled Tasks**")
            st.caption("Submits a new SLURM array job for selected subjects only.")

            if not restartable:
                st.info("No failed or cancelled tasks to restart.")
            elif not is_real_job:
                st.info("Cannot restart from reconciled state.")
            else:
                restart_options = {
                    f"sub-{s.subject_id} ({s.status.value})": s.subject_id
                    for s in restartable
                }
                restart_defaults = list(restart_options.keys())
                to_restart = st.multiselect(
                    "Select subjects to restart",
                    options=restart_defaults,
                    default=restart_defaults,
                    key="restart_subject_select",
                )
                restart_ids = [restart_options[label] for label in to_restart]

                if st.button(
                    "Restart Selected", disabled=not to_restart,
                    type="primary", key="restart_btn"
                ):
                    original_script = _recover_original_script(state, config)
                    if original_script:
                        st.session_state.hpc_workflow_state = state
                        _save_state_to_disk(state, config)

                    if not original_script:
                        st.error(
                            "Could not recover the original SLURM script from state or HPC. "
                            "Please re-submit the job manually."
                        )
                    else:
                        # Warn if any selected subjects are still active
                        active_ids = {
                            s.subject_id for s in state.job_statuses
                            if s.status in {JobStatus.RUNNING, JobStatus.PENDING, JobStatus.COMPLETING}
                        }
                        overlap = [sid for sid in restart_ids if sid in active_ids]
                        if overlap:
                            st.warning(
                                f"Subjects still active in SLURM: {', '.join(overlap)}. "
                                "Kill them first to avoid output conflicts."
                            )
                        else:
                            try:
                                hpc_config = HPCConfig.from_config(config)
                                manager = HPCWorkflowManager(
                                    hpc_config=hpc_config,
                                    local_bids=config.get('paths', {}).get('bids_dir', ''),
                                    local_output=config.get('paths', {}).get('fmriprep_dir', ''),
                                )
                                restart_index = len(state.restart_jobs)
                                with st.spinner(f"Submitting restart wave {restart_index + 1}..."):
                                    new_job_id = manager.submit_restart_job(
                                        subjects=restart_ids,
                                        original_script_content=original_script,
                                        restart_index=restart_index,
                                    )

                                wave = {
                                    "job_id": new_job_id,
                                    "subjects": restart_ids,
                                    "submitted_at": datetime.now().isoformat(timespec="seconds"),
                                }
                                state.restart_jobs.append(wave)
                                st.session_state.hpc_workflow_state = state
                                _save_state_to_disk(state, config)

                                st.success(
                                    f"Restart job submitted: **{new_job_id}** "
                                    f"({len(restart_ids)} subjects). "
                                    "Click **Refresh Status** to track progress."
                                )
                                st.rerun()
                            except Exception as e:
                                st.error(f"Restart submission failed: {e}")
                                import traceback
                                st.code(traceback.format_exc())

        # ── Restart history ──────────────────────────────────────
        if state.restart_jobs:
            st.divider()
            st.markdown(f"**Restart history** ({len(state.restart_jobs)} wave(s))")
            for i, wave in enumerate(state.restart_jobs, 1):
                n_subs = len(wave.get('subjects', []))
                st.caption(
                    f"Wave {i} — Job {wave.get('job_id', '?')} — "
                    f"{n_subs} subject(s) — submitted {wave.get('submitted_at', '?')}"
                )


def render_download_cleanup(config: Dict):
    """Render download and cleanup interface."""
    st.subheader("Download & Cleanup")

    state = st.session_state.get('hpc_workflow_state')

    if not state or not state.job_id:
        st.info("No workflow state. Complete upload and processing first.")
        return

    # Allow access in monitor/download/cleanup/completed steps
    valid_steps = {'monitor', 'download', 'cleanup', 'completed'}
    if state.current_step not in valid_steps:
        st.info(f"Processing not yet complete. Current step: {state.current_step}")

        # Manual override button if job_id exists but step is wrong
        if state.job_id:
            st.warning(f"Job **{state.job_id}** exists but current step is '{state.current_step}'.")
            if st.button("⚡ Force Enable Download", help="Override step and enable download tab"):
                state.current_step = 'download'
                st.session_state.hpc_workflow_state = state
                _save_state_to_disk(state, config)
                st.success("Download step enabled. Refresh or interact to continue.")
                st.rerun()
        return

    # Download section
    st.markdown("### Download Results")

    can_download = state.current_step in ['download', 'cleanup', 'completed']

    # Get successful subjects
    successful_subjects = [
        s.subject_id for s in state.job_statuses
        if s.status == JobStatus.COMPLETED
    ] if state.job_statuses else state.subjects

    if successful_subjects:
        st.info(f"Ready to download: {len(successful_subjects)} subjects")
    else:
        st.warning("No successful subjects to download.")

    col1, col2 = st.columns(2)

    with col1:
        download_btn = st.button(
            "Download Results",
            type="primary" if can_download else "secondary",
            disabled=not can_download or not successful_subjects,
            help="Download fMRIPrep outputs from HPC"
        )

    with col2:
        if state.download_progress:
            completed = sum(1 for s in state.download_progress.values() if s == 'Complete')
            st.progress(completed / len(successful_subjects), text=f"Downloaded: {completed}/{len(successful_subjects)}")

    if download_btn and can_download and successful_subjects:
        try:
            hpc_config = HPCConfig.from_config(config)
            manager = HPCWorkflowManager(
                hpc_config=hpc_config,
                local_bids=config.get('paths', {}).get('bids_dir', ''),
                local_output=config.get('paths', {}).get('fmriprep_dir', '')
            )

            progress_placeholder = st.empty()

            def download_callback(sub_id, status, progress):
                state.download_progress[sub_id] = status
                progress_placeholder.progress(progress, text=f"Downloading sub-{sub_id}: {status}")

            with st.spinner("Downloading results..."):
                results = manager.download_results(successful_subjects, progress_callback=download_callback)

            downloaded = sum(1 for ok in results.values() if ok)
            failed = sum(1 for ok in results.values() if not ok)

            if failed > 0:
                state.errors.append(f"Download failed for {failed} subjects")

            state.current_step = 'cleanup'
            st.session_state.hpc_workflow_state = state
            _save_state_to_disk(state, config)

            st.success(f"Download complete: {downloaded}/{len(successful_subjects)} subjects")
            st.rerun()

        except Exception as e:
            st.error(f"Download error: {e}")
            import traceback
            st.code(traceback.format_exc())

    # Cleanup section
    st.markdown("---")
    st.markdown("### Cleanup Remote Files")

    can_cleanup = state.current_step in ['cleanup', 'completed']

    col1, col2, col3 = st.columns(3)

    with col1:
        cleanup_bids = st.checkbox("BIDS data", value=True, help="Remove uploaded BIDS data")
    with col2:
        cleanup_deriv = st.checkbox("Derivatives", value=True, help="Remove fMRIPrep outputs")
    with col3:
        cleanup_work = st.checkbox("Work directories", value=True, help="Remove work directories")

    cleanup_btn = st.button(
        "Cleanup Remote",
        type="secondary",
        disabled=not can_cleanup,
        help="Remove files from HPC"
    )

    if cleanup_btn and can_cleanup:
        try:
            hpc_config = HPCConfig.from_config(config)
            manager = HPCWorkflowManager(
                hpc_config=hpc_config,
                local_bids=config.get('paths', {}).get('bids_dir', ''),
                local_output=config.get('paths', {}).get('fmriprep_dir', '')
            )

            with st.spinner("Cleaning up remote files..."):
                results = manager.cleanup_remote(
                    state.subjects,
                    cleanup_bids=cleanup_bids,
                    cleanup_derivatives=cleanup_deriv,
                    cleanup_work=cleanup_work
                )

            cleaned = sum(1 for ok in results.values() if ok)
            state.current_step = 'completed'
            st.session_state.hpc_workflow_state = state
            _save_state_to_disk(state, config)

            st.success(f"Cleanup complete: {cleaned}/{len(state.subjects)} subjects")

        except Exception as e:
            st.error(f"Cleanup error: {e}")

    # Reset workflow button
    st.markdown("---")
    if st.button("Reset Workflow", help="Clear current workflow state to start fresh"):
        st.session_state.hpc_workflow_state = None
        _clear_state_from_disk(config)
        st.success("Workflow reset.")
        st.rerun()


def render():
    """Main render function for HPC Submit page."""
    st.header("HPC Submit - fMRIPrep")

    # Get config
    config = st.session_state.get('config', {})

    if not config:
        st.error("No configuration loaded. Please check Settings.")
        return

    # Restore workflow state from disk if not in session_state
    if 'hpc_workflow_state' not in st.session_state:
        disk_state = _load_state_from_disk(config)
        if disk_state and disk_state.job_id:
            script_was_missing = not disk_state.original_script
            recovered_script = _recover_original_script(disk_state, config)
            st.session_state.hpc_workflow_state = disk_state
            if script_was_missing and recovered_script:
                _save_state_to_disk(disk_state, config)
            st.info(f"ℹ️ Restored previous job state: Job **{disk_state.job_id}** ({disk_state.current_step})")

    # Check HPC configuration
    hpc_config = config.get('hpc', {})
    if not hpc_config.get('enabled', False):
        st.warning("HPC is not enabled in your configuration.")
        st.info("""
        To enable HPC processing:
        1. Go to Settings
        2. Enable HPC and configure connection details
        3. Or edit your project YAML file directly
        """)

        # Show example config
        with st.expander("Example HPC Configuration"):
            st.code("""
hpc:
  enabled: true
  host: "hpclogin1.example.edu"
  user: "username"
  ssh_key: null  # Use ssh-agent

  remote_paths:
    base: "/home/username/project"
    bids: "${base}/bids"
    fmriprep: "${base}/fmriprep"
    work: "${base}/work"

  singularity_images:
    fmriprep: "/path/to/fmriprep-25.2.5.simg"
    freesurfer_license: "/path/to/license.txt"

  slurm:
    partition: "shared_cpu"
    default_cpus: 8
    default_memory: "32GB"
    default_time: "24:00:00"
    max_concurrent_jobs: 4
            """, language="yaml")
        return

    # Test connection button
    with st.expander("Test HPC Connection"):
        if st.button("Test Connection"):
            try:
                from utils.hpc import HPCConfig, HPCConnection
                hpc_cfg = HPCConfig.from_config(config)

                with st.spinner(f"Connecting to {hpc_cfg.host}..."):
                    conn = HPCConnection(hpc_cfg)
                    conn.connect()
                    stdout, stderr, exit_code = conn.execute("hostname && whoami")
                    conn.disconnect()

                if exit_code == 0:
                    st.success(f"Connection successful!\n{stdout}")
                else:
                    st.error(f"Connection test failed: {stderr}")

            except Exception as e:
                st.error(f"Connection failed: {e}")

    # Create tabs for workflow
    tabs = st.tabs([
        "1. Subject Selection",
        "2. Configuration",
        "3. Upload & Submit",
        "4. Monitor",
        "5. Download & Cleanup",
        "🖥️ Cluster Status"
    ])

    # Tab 1: Subject Selection
    with tabs[0]:
        selected_subjects = render_subject_selection(config)
        if selected_subjects:
            st.session_state.hpc_selected_subjects = selected_subjects

    # Tab 2: Configuration
    with tabs[1]:
        subjects = st.session_state.get('hpc_selected_subjects', [])
        if not subjects:
            st.warning("Please select subjects in Tab 1 first.")
        else:
            slurm_config = render_configuration(config)
            if slurm_config:
                st.session_state.hpc_slurm_config = slurm_config

                # Show script preview
                st.markdown("---")
                render_script_preview(config, subjects, slurm_config)

    # Tab 3: Upload & Submit
    with tabs[2]:
        subjects = st.session_state.get('hpc_selected_subjects', [])
        slurm_config = st.session_state.get('hpc_slurm_config')

        if not subjects:
            st.warning("Please select subjects in Tab 1 first.")
        elif not slurm_config:
            st.warning("Please configure settings in Tab 2 first.")
        else:
            render_upload_submit(config, subjects, slurm_config)

    # Tab 4: Monitor
    with tabs[3]:
        render_monitor(config)

    # Tab 5: Download & Cleanup
    with tabs[4]:
        render_download_cleanup(config)

    with tabs[5]:
        render_cluster_status(config)

    # Workflow state sidebar
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Workflow State")

    state = st.session_state.get('hpc_workflow_state')
    if state:
        st.sidebar.text(f"Step: {state.current_step}")
        st.sidebar.text(f"Job ID: {state.job_id or 'N/A'}")
        st.sidebar.text(f"Subjects: {len(state.subjects)}")

        if state.job_statuses:
            completed = sum(1 for s in state.job_statuses if s.status == JobStatus.COMPLETED)
            st.sidebar.text(f"Completed: {completed}/{len(state.job_statuses)}")
    else:
        st.sidebar.text("No active workflow")


if __name__ == "__main__":
    render()
