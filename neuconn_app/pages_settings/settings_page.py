"""
Settings Page Implementation

Comprehensive configuration editor for NeuConn app:
- Project settings (name, description)
- Path settings with validation
- HPC settings (collapsible)
- Analysis parameters
- QC profiles editor
- Import/Export functionality

Implementation: Phase 1
"""

import streamlit as st
from pathlib import Path
from typing import Dict, Any, Tuple, List
import yaml
import copy
import os


def render():
    """Main settings page render function."""
    from utils.config import load_config, save_config, merge_configs

    st.title("Settings")

    # Determine config file path
    config_path = Path.home() / "neuconn_projects" / "longevity.yaml"
    default_config_path = Path(__file__).parent.parent / "config" / "default_config.yaml"

    # Show current config file being edited
    st.info(f"Editing: {config_path}")

    # Load current config
    if 'settings_config' not in st.session_state:
        st.session_state.settings_config = load_config(str(config_path))

    config = st.session_state.settings_config

    # Create tabs for organization
    tab_project, tab_paths, tab_hpc, tab_analysis, tab_qc, tab_actions = st.tabs([
        "Project",
        "Paths",
        "HPC Settings",
        "Analysis Parameters",
        "QC Profiles",
        "Import/Export"
    ])

    # Track if any changes were made
    changes_made = False

    with tab_project:
        changes_made |= render_project_settings(config)

    with tab_paths:
        changes_made |= render_path_settings(config)

    with tab_hpc:
        changes_made |= render_hpc_settings(config)

    with tab_analysis:
        changes_made |= render_analysis_settings(config)

    with tab_qc:
        changes_made |= render_qc_profiles(config)

    with tab_actions:
        render_import_export(config, config_path, default_config_path)

    # Save button (always visible at bottom)
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("Save Configuration", type="primary", use_container_width=True):
            try:
                save_config(config, str(config_path))
                # Update main session state config
                st.session_state.config = config.copy()
                st.success(f"Configuration saved to {config_path}")
            except Exception as e:
                st.error(f"Error saving configuration: {e}")

    with col2:
        if st.button("Reset to Defaults", use_container_width=True):
            try:
                with open(default_config_path, 'r') as f:
                    default_config = yaml.safe_load(f)
                st.session_state.settings_config = default_config
                st.rerun()
            except Exception as e:
                st.error(f"Error loading defaults: {e}")


def render_project_settings(config: Dict) -> bool:
    """Render project settings section."""
    st.subheader("Project Settings")

    changes = False

    # Ensure project section exists
    if 'project' not in config:
        config['project'] = {}

    with st.form("project_settings_form"):
        new_name = st.text_input(
            "Project Name",
            value=config['project'].get('name', 'My BIDS Project'),
            help="Name of your neuroimaging project"
        )

        new_desc = st.text_area(
            "Description",
            value=config['project'].get('description', ''),
            help="Brief description of the study",
            height=100
        )

        if st.form_submit_button("Apply Project Settings"):
            if new_name != config['project'].get('name'):
                config['project']['name'] = new_name
                changes = True
            if new_desc != config['project'].get('description'):
                config['project']['description'] = new_desc
                changes = True
            if changes:
                st.success("Project settings updated (remember to save)")

    return changes


def validate_path(path_str: str) -> Tuple[bool, str]:
    """Validate a path exists."""
    if not path_str:
        return False, "Path is empty"

    # Expand user home directory
    expanded = os.path.expanduser(path_str)

    # Handle ${variable} placeholders - can't validate these
    if '${' in expanded:
        return True, "Contains variable reference (cannot validate)"

    path = Path(expanded)
    if path.exists():
        return True, "Path exists"
    else:
        return False, "Path does not exist"


def render_path_settings(config: Dict) -> bool:
    """Render path settings with validation."""
    st.subheader("Path Settings")

    changes = False

    # Ensure paths section exists
    if 'paths' not in config:
        config['paths'] = {}

    paths = config['paths']

    # Define path fields with descriptions
    path_fields = [
        ('bids_dir', 'BIDS Directory', 'Root directory containing BIDS-formatted data'),
        ('derivatives_dir', 'Derivatives Directory', 'Output directory for preprocessing results'),
        ('fmriprep_dir', 'fMRIPrep Directory', 'fMRIPrep output location (can use ${derivatives_dir})'),
        ('qsiprep_dir', 'QSIPrep Directory', 'QSIPrep output location (can use ${derivatives_dir})'),
        ('excluded_dir', 'Excluded Scans Directory', 'Directory for excluded/problematic scans'),
        ('atlases_dir', 'Atlases Directory', 'Brain atlas files (Schaefer, DiFuMo, etc.)'),
        ('temp_dir', 'Temporary Directory', 'Working directory for intermediate files'),
        ('cache_dir', 'Cache Directory', 'Cache for processed images and data'),
    ]

    with st.form("path_settings_form"):
        new_values = {}

        for key, label, help_text in path_fields:
            col1, col2 = st.columns([5, 1])

            current_value = paths.get(key, '')

            with col1:
                new_values[key] = st.text_input(
                    label,
                    value=current_value,
                    help=help_text,
                    key=f"path_{key}"
                )

            with col2:
                # Validation indicator
                is_valid, msg = validate_path(current_value)
                if is_valid:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if "variable" in msg:
                        st.markdown("**~**")
                    else:
                        st.markdown("**OK**")
                else:
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("**X**")

        if st.form_submit_button("Apply Path Settings"):
            for key, _, _ in path_fields:
                if new_values[key] != paths.get(key, ''):
                    paths[key] = new_values[key]
                    changes = True
            if changes:
                st.success("Path settings updated (remember to save)")

    # Validate BIDS directory
    st.markdown("---")
    st.markdown("**Path Validation**")

    bids_path = paths.get('bids_dir', '')
    if bids_path and '${' not in bids_path:
        expanded_bids = os.path.expanduser(bids_path)
        if Path(expanded_bids).exists():
            # Check if it looks like a BIDS directory
            has_participants = (Path(expanded_bids) / "participants.tsv").exists()
            has_dataset_desc = (Path(expanded_bids) / "dataset_description.json").exists()
            has_subjects = any((Path(expanded_bids)).glob("sub-*"))

            col1, col2, col3 = st.columns(3)
            with col1:
                if has_subjects:
                    st.success("Subject directories found")
                else:
                    st.warning("No sub-* directories found")
            with col2:
                if has_dataset_desc:
                    st.success("dataset_description.json found")
                else:
                    st.warning("Missing dataset_description.json")
            with col3:
                if has_participants:
                    st.success("participants.tsv found")
                else:
                    st.info("No participants.tsv (optional)")
        else:
            st.error(f"BIDS directory does not exist: {expanded_bids}")

    return changes


def render_hpc_settings(config: Dict) -> bool:
    """Render HPC settings in collapsible sections."""
    st.subheader("HPC Settings")

    changes = False

    # Ensure HPC section exists
    if 'hpc' not in config:
        config['hpc'] = {'enabled': False}

    hpc = config['hpc']

    # Main HPC enable toggle
    hpc_enabled = st.checkbox(
        "Enable HPC Processing",
        value=hpc.get('enabled', False),
        help="Enable remote processing on HPC cluster via SSH"
    )

    if hpc_enabled != hpc.get('enabled'):
        hpc['enabled'] = hpc_enabled
        changes = True

    if not hpc_enabled:
        st.info("HPC processing is disabled. Enable to configure remote processing settings.")
        return changes

    # Connection settings
    with st.expander("Connection Settings", expanded=True):
        with st.form("hpc_connection_form"):
            col1, col2 = st.columns(2)

            with col1:
                new_host = st.text_input(
                    "HPC Host",
                    value=hpc.get('host', ''),
                    help="SSH hostname (e.g., hpclogin1.eduhk.hk)"
                )
                new_user = st.text_input(
                    "Username",
                    value=hpc.get('user', ''),
                    help="SSH username on HPC"
                )

            with col2:
                new_ssh_key = st.text_input(
                    "SSH Key Path (optional)",
                    value=hpc.get('ssh_key') or '',
                    help="Path to SSH private key (leave empty to use ssh-agent)"
                )

            if st.form_submit_button("Apply Connection Settings"):
                if new_host != hpc.get('host'):
                    hpc['host'] = new_host
                    changes = True
                if new_user != hpc.get('user'):
                    hpc['user'] = new_user
                    changes = True
                ssh_key_val = new_ssh_key if new_ssh_key else None
                if ssh_key_val != hpc.get('ssh_key'):
                    hpc['ssh_key'] = ssh_key_val
                    changes = True
                if changes:
                    st.success("Connection settings updated")

        # Test connection button
        if st.button("Test Connection"):
            test_hpc_connection(hpc)

    # Remote paths
    with st.expander("Remote Paths"):
        if 'remote_paths' not in hpc:
            hpc['remote_paths'] = {}
        remote = hpc['remote_paths']

        with st.form("hpc_remote_paths_form"):
            remote_fields = [
                ('base', 'Base Path', 'Root directory on HPC'),
                ('bids', 'BIDS Path', 'Remote BIDS directory (can use ${base})'),
                ('fmriprep', 'fMRIPrep Output', 'Remote fMRIPrep output directory'),
                ('work', 'Work Directory', 'Temporary work directory on HPC'),
            ]

            new_remote = {}
            for key, label, help_text in remote_fields:
                new_remote[key] = st.text_input(
                    label,
                    value=remote.get(key, ''),
                    help=help_text,
                    key=f"remote_{key}"
                )

            if st.form_submit_button("Apply Remote Paths"):
                for key, _, _ in remote_fields:
                    if new_remote[key] != remote.get(key, ''):
                        remote[key] = new_remote[key]
                        changes = True
                if changes:
                    st.success("Remote paths updated")

    # Singularity images
    with st.expander("Singularity Images"):
        if 'singularity_images' not in hpc:
            hpc['singularity_images'] = {}
        simg = hpc['singularity_images']

        with st.form("hpc_singularity_form"):
            simg_fields = [
                ('fmriprep', 'fMRIPrep Image', 'Path to fMRIPrep .simg/.sif'),
                ('fmripost_aroma', 'fMRIPost-AROMA Image', 'Path to fMRIPost-AROMA .sif'),
                ('qsiprep', 'QSIPrep Image', 'Path to QSIPrep .sif'),
                ('qsirecon', 'QSIRecon Image', 'Path to QSIRecon .sif'),
                ('freesurfer_license', 'FreeSurfer License', 'Path to FreeSurfer license.txt'),
            ]

            new_simg = {}
            for key, label, help_text in simg_fields:
                new_simg[key] = st.text_input(
                    label,
                    value=simg.get(key, ''),
                    help=help_text,
                    key=f"simg_{key}"
                )

            if st.form_submit_button("Apply Singularity Paths"):
                for key, _, _ in simg_fields:
                    if new_simg[key] != simg.get(key, ''):
                        simg[key] = new_simg[key]
                        changes = True
                if changes:
                    st.success("Singularity paths updated")

    # SLURM settings
    with st.expander("SLURM Settings"):
        if 'slurm' not in hpc:
            hpc['slurm'] = {}
        slurm = hpc['slurm']

        with st.form("hpc_slurm_form"):
            col1, col2 = st.columns(2)

            with col1:
                new_partition = st.text_input(
                    "Partition",
                    value=slurm.get('partition', 'shared_cpu'),
                    help="SLURM partition name"
                )
                new_cpus = st.number_input(
                    "CPUs per Job",
                    min_value=1,
                    max_value=64,
                    value=slurm.get('default_cpus', 8),
                    help="Number of CPU cores per job"
                )
                new_memory = st.text_input(
                    "Memory per Job",
                    value=slurm.get('default_memory', '32GB'),
                    help="Memory allocation (e.g., 32GB)"
                )

            with col2:
                new_time = st.text_input(
                    "Time Limit",
                    value=slurm.get('default_time', '24:00:00'),
                    help="Wall time limit (HH:MM:SS)"
                )
                new_max_jobs = st.number_input(
                    "Max Concurrent Jobs",
                    min_value=1,
                    max_value=20,
                    value=slurm.get('max_concurrent_jobs', 4),
                    help="Maximum number of simultaneous jobs"
                )
                new_batch_size = st.number_input(
                    "Batch Size",
                    min_value=1,
                    max_value=20,
                    value=slurm.get('batch_size', 4),
                    help="Number of subjects per batch"
                )

            if st.form_submit_button("Apply SLURM Settings"):
                updates = {
                    'partition': new_partition,
                    'default_cpus': new_cpus,
                    'default_memory': new_memory,
                    'default_time': new_time,
                    'max_concurrent_jobs': new_max_jobs,
                    'batch_size': new_batch_size,
                }
                for key, val in updates.items():
                    if val != slurm.get(key):
                        slurm[key] = val
                        changes = True
                if changes:
                    st.success("SLURM settings updated")

    # Validation warnings
    if hpc_enabled:
        warnings = []
        if not hpc.get('host'):
            warnings.append("HPC host is not configured")
        if not hpc.get('user'):
            warnings.append("HPC username is not configured")
        if not hpc.get('singularity_images', {}).get('fmriprep'):
            warnings.append("fMRIPrep Singularity image path is not set")

        if warnings:
            st.warning("**Configuration Warnings:**\n- " + "\n- ".join(warnings))

    return changes


def test_hpc_connection(hpc_config: Dict):
    """Test HPC SSH connection."""
    host = hpc_config.get('host')
    user = hpc_config.get('user')

    if not host or not user:
        st.error("Host and username are required to test connection")
        return

    st.info(f"Testing connection to {user}@{host}...")

    try:
        import paramiko

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Connection parameters
        connect_kwargs = {
            'hostname': host,
            'username': user,
            'timeout': 10,
        }

        ssh_key = hpc_config.get('ssh_key')
        if ssh_key:
            connect_kwargs['key_filename'] = os.path.expanduser(ssh_key)

        ssh.connect(**connect_kwargs)

        # Test a simple command
        stdin, stdout, stderr = ssh.exec_command('hostname')
        remote_hostname = stdout.read().decode().strip()

        ssh.close()

        st.success(f"Connection successful! Connected to: {remote_hostname}")

    except paramiko.AuthenticationException:
        st.error("Authentication failed. Check your username and SSH key/agent.")
    except paramiko.SSHException as e:
        st.error(f"SSH error: {e}")
    except Exception as e:
        st.error(f"Connection failed: {e}")


def render_analysis_settings(config: Dict) -> bool:
    """Render analysis parameter settings."""
    st.subheader("Analysis Parameters")

    changes = False

    # fMRIPrep settings
    with st.expander("fMRIPrep Settings", expanded=True):
        if 'fmriprep' not in config:
            config['fmriprep'] = {}
        fmriprep = config['fmriprep']

        with st.form("fmriprep_form"):
            new_version = st.text_input(
                "fMRIPrep Version",
                value=fmriprep.get('version', '25.2.5'),
                help="Version of fMRIPrep to use"
            )

            # Output spaces as multiselect
            available_spaces = [
                "MNI152NLin2009cAsym:res-2",
                "MNI152NLin6Asym:res-2",
                "MNI152NLin2009cAsym:res-native",
                "T1w",
                "fsnative",
                "fsaverage",
                "fsaverage5",
                "fsaverage6",
            ]
            current_spaces = fmriprep.get('output_spaces', [])
            new_spaces = st.multiselect(
                "Output Spaces",
                options=available_spaces,
                default=[s for s in current_spaces if s in available_spaces],
                help="Select output space templates"
            )

            # Custom spaces
            custom_spaces = st.text_input(
                "Additional Custom Spaces (comma-separated)",
                value=",".join([s for s in current_spaces if s not in available_spaces]),
                help="Add spaces not in the list above"
            )

            # Flags
            current_flags = fmriprep.get('flags', [])
            new_flags = st.text_area(
                "fMRIPrep Flags (one per line)",
                value="\n".join(current_flags),
                help="Additional command-line flags for fMRIPrep",
                height=100
            )

            if st.form_submit_button("Apply fMRIPrep Settings"):
                if new_version != fmriprep.get('version'):
                    fmriprep['version'] = new_version
                    changes = True

                # Combine standard and custom spaces
                all_spaces = new_spaces.copy()
                if custom_spaces.strip():
                    all_spaces.extend([s.strip() for s in custom_spaces.split(',') if s.strip()])

                if all_spaces != current_spaces:
                    fmriprep['output_spaces'] = all_spaces
                    changes = True

                new_flags_list = [f.strip() for f in new_flags.split('\n') if f.strip()]
                if new_flags_list != current_flags:
                    fmriprep['flags'] = new_flags_list
                    changes = True

                if changes:
                    st.success("fMRIPrep settings updated")

    # Connectivity settings
    with st.expander("Connectivity Analysis Settings"):
        if 'connectivity' not in config:
            config['connectivity'] = {}
        conn = config['connectivity']

        if 'local_measures' not in conn:
            conn['local_measures'] = {}
        local = conn['local_measures']

        with st.form("connectivity_form"):
            col1, col2 = st.columns(2)

            with col1:
                # TR setting with auto-detect toggle
                auto_tr = st.checkbox(
                    "Auto-detect TR from BIDS",
                    value=local.get('tr') is None,
                    help="Automatically detect TR from sidecar JSON files"
                )

                if auto_tr:
                    new_tr = None
                    st.info("TR will be auto-detected from BIDS sidecar files")
                else:
                    new_tr = st.number_input(
                        "TR (seconds)",
                        min_value=0.1,
                        max_value=10.0,
                        value=float(local.get('tr', 2.0)) if local.get('tr') else 2.0,
                        step=0.1,
                        help="Repetition time in seconds"
                    )

                new_smoothing = st.number_input(
                    "Smoothing FWHM (mm)",
                    min_value=0.0,
                    max_value=20.0,
                    value=float(local.get('smoothing_fwhm', 6)),
                    step=0.5,
                    help="Spatial smoothing full-width half-maximum"
                )

            with col2:
                # Bandpass filter
                current_bp = local.get('bandpass', [0.01, 0.1])
                new_bp_low = st.number_input(
                    "Bandpass Low (Hz)",
                    min_value=0.001,
                    max_value=0.1,
                    value=float(current_bp[0]) if current_bp else 0.01,
                    step=0.005,
                    format="%.3f",
                    help="Lower cutoff frequency"
                )
                new_bp_high = st.number_input(
                    "Bandpass High (Hz)",
                    min_value=0.05,
                    max_value=0.5,
                    value=float(current_bp[1]) if current_bp else 0.1,
                    step=0.01,
                    format="%.2f",
                    help="Upper cutoff frequency"
                )

            if st.form_submit_button("Apply Connectivity Settings"):
                if new_tr != local.get('tr'):
                    local['tr'] = new_tr
                    changes = True
                if new_smoothing != local.get('smoothing_fwhm'):
                    local['smoothing_fwhm'] = new_smoothing
                    changes = True
                new_bp = [new_bp_low, new_bp_high]
                if new_bp != local.get('bandpass'):
                    local['bandpass'] = new_bp
                    changes = True

                if changes:
                    st.success("Connectivity settings updated")

    # Group analysis settings
    with st.expander("Group Analysis Settings"):
        if 'group_analysis' not in config:
            config['group_analysis'] = {}
        group = config['group_analysis']

        with st.form("group_analysis_form"):
            new_model = st.text_input(
                "Statistical Model",
                value=group.get('statistical_model', 'value ~ Group * Time + Age + Sex + MeanFD + (1|Subject)'),
                help="R-style formula for linear mixed-effects model"
            )

            col1, col2 = st.columns(2)

            with col1:
                available_corrections = ["FWE", "FDR", "uncorrected"]
                current_corrections = group.get('correction_methods', ['FWE', 'FDR', 'uncorrected'])
                new_corrections = st.multiselect(
                    "Correction Methods",
                    options=available_corrections,
                    default=current_corrections,
                    help="Multiple comparison correction methods"
                )

                new_cluster_thresh = st.number_input(
                    "Cluster Threshold (voxels)",
                    min_value=1,
                    max_value=500,
                    value=group.get('cluster_threshold', 50),
                    help="Minimum cluster size in voxels"
                )

            with col2:
                new_perms = st.number_input(
                    "Permutations",
                    min_value=100,
                    max_value=50000,
                    value=group.get('permutations', 5000),
                    step=100,
                    help="Number of permutations for non-parametric testing"
                )

            if st.form_submit_button("Apply Group Analysis Settings"):
                if new_model != group.get('statistical_model'):
                    group['statistical_model'] = new_model
                    changes = True
                if new_corrections != group.get('correction_methods'):
                    group['correction_methods'] = new_corrections
                    changes = True
                if new_cluster_thresh != group.get('cluster_threshold'):
                    group['cluster_threshold'] = new_cluster_thresh
                    changes = True
                if new_perms != group.get('permutations'):
                    group['permutations'] = new_perms
                    changes = True

                if changes:
                    st.success("Group analysis settings updated")

    return changes


def render_qc_profiles(config: Dict) -> bool:
    """Render QC profiles editor."""
    st.subheader("QC Profiles")

    st.markdown("""
    QC profiles define thresholds for motion and signal quality checks.
    Different profiles can be used for different analysis sensitivity requirements.
    """)

    changes = False

    # Ensure group_analysis and qc_profiles exist
    if 'group_analysis' not in config:
        config['group_analysis'] = {}
    if 'qc_profiles' not in config['group_analysis']:
        config['group_analysis']['qc_profiles'] = {}

    profiles = config['group_analysis']['qc_profiles']

    # Display existing profiles
    profile_names = list(profiles.keys())

    if profile_names:
        st.markdown("**Existing Profiles:**")

        for profile_key in profile_names:
            profile = profiles[profile_key]

            with st.expander(f"{profile.get('name', profile_key)} - {profile.get('description', '')}"):
                with st.form(f"profile_form_{profile_key}"):
                    col1, col2 = st.columns(2)

                    with col1:
                        new_name = st.text_input(
                            "Profile Name",
                            value=profile.get('name', profile_key),
                            key=f"profile_name_{profile_key}"
                        )
                        new_desc = st.text_input(
                            "Description",
                            value=profile.get('description', ''),
                            key=f"profile_desc_{profile_key}"
                        )
                        new_fd_thresh = st.number_input(
                            "FD Threshold (mm)",
                            min_value=0.1,
                            max_value=2.0,
                            value=float(profile.get('fd_threshold', 0.5)),
                            step=0.1,
                            key=f"profile_fd_{profile_key}"
                        )
                        new_fd_metric = st.selectbox(
                            "FD Metric",
                            options=["mean", "median", "max"],
                            index=["mean", "median", "max"].index(profile.get('fd_metric', 'mean')),
                            key=f"profile_fd_metric_{profile_key}"
                        )

                    with col2:
                        new_min_vol = st.number_input(
                            "Minimum Volumes",
                            min_value=100,
                            max_value=1000,
                            value=profile.get('min_volumes', 350),
                            key=f"profile_vol_{profile_key}"
                        )
                        new_tsnr = st.number_input(
                            "tSNR Threshold",
                            min_value=10.0,
                            max_value=100.0,
                            value=float(profile.get('tsnr_threshold', 30)),
                            step=5.0,
                            key=f"profile_tsnr_{profile_key}"
                        )
                        new_exclude = st.checkbox(
                            "Exclude if Missing Data",
                            value=profile.get('exclude_if_missing', False),
                            key=f"profile_exclude_{profile_key}"
                        )

                    col_save, col_delete = st.columns(2)

                    with col_save:
                        if st.form_submit_button("Update Profile"):
                            profile['name'] = new_name
                            profile['description'] = new_desc
                            profile['fd_threshold'] = new_fd_thresh
                            profile['fd_metric'] = new_fd_metric
                            profile['min_volumes'] = new_min_vol
                            profile['tsnr_threshold'] = new_tsnr
                            profile['exclude_if_missing'] = new_exclude
                            changes = True
                            st.success(f"Profile '{new_name}' updated")

                    with col_delete:
                        if st.form_submit_button("Delete Profile", type="secondary"):
                            del profiles[profile_key]
                            changes = True
                            st.rerun()

    # Add new profile
    st.markdown("---")
    st.markdown("**Add New Profile:**")

    with st.form("new_profile_form"):
        col1, col2 = st.columns(2)

        with col1:
            new_key = st.text_input(
                "Profile Key (lowercase, no spaces)",
                value="",
                help="Internal identifier for the profile"
            )
            new_name = st.text_input(
                "Display Name",
                value=""
            )
            new_desc = st.text_input(
                "Description",
                value=""
            )

        with col2:
            new_fd = st.number_input(
                "FD Threshold",
                min_value=0.1,
                max_value=2.0,
                value=0.5,
                step=0.1
            )
            new_tsnr = st.number_input(
                "tSNR Threshold",
                min_value=10.0,
                max_value=100.0,
                value=30.0
            )
            new_min_vol = st.number_input(
                "Min Volumes",
                min_value=100,
                max_value=1000,
                value=350
            )

        if st.form_submit_button("Add Profile"):
            if new_key and new_key not in profiles:
                profiles[new_key] = {
                    'name': new_name or new_key,
                    'description': new_desc,
                    'fd_threshold': new_fd,
                    'fd_metric': 'mean',
                    'min_volumes': new_min_vol,
                    'tsnr_threshold': new_tsnr,
                    'exclude_if_missing': False,
                }
                changes = True
                st.success(f"Profile '{new_name or new_key}' added")
                st.rerun()
            elif not new_key:
                st.error("Profile key is required")
            else:
                st.error(f"Profile '{new_key}' already exists")

    return changes


def render_import_export(config: Dict, config_path: Path, default_config_path: Path):
    """Render import/export functionality."""
    st.subheader("Import / Export Configuration")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Export Configuration**")

        # Generate YAML content
        yaml_content = yaml.dump(config, default_flow_style=False, sort_keys=False)

        st.download_button(
            label="Download YAML",
            data=yaml_content,
            file_name=f"{config.get('project', {}).get('name', 'config').replace(' ', '_').lower()}_config.yaml",
            mime="text/yaml",
            use_container_width=True
        )

        # Show current config preview
        with st.expander("Preview Current Configuration"):
            st.code(yaml_content, language="yaml")

    with col2:
        st.markdown("**Import Configuration**")

        uploaded_file = st.file_uploader(
            "Upload YAML Configuration",
            type=['yaml', 'yml'],
            help="Upload a previously exported configuration file"
        )

        if uploaded_file is not None:
            try:
                uploaded_config = yaml.safe_load(uploaded_file.read())

                st.success("File loaded successfully!")

                with st.expander("Preview Uploaded Configuration"):
                    st.code(yaml.dump(uploaded_config, default_flow_style=False), language="yaml")

                if st.button("Apply Uploaded Configuration", type="primary"):
                    st.session_state.settings_config = uploaded_config
                    st.rerun()

            except yaml.YAMLError as e:
                st.error(f"Invalid YAML file: {e}")
            except Exception as e:
                st.error(f"Error loading file: {e}")

    st.markdown("---")

    # Config file info
    st.markdown("**Configuration Files**")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(f"**Current Config:**  \n`{config_path}`")
        if config_path.exists():
            stat = config_path.stat()
            from datetime import datetime
            mod_time = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            st.caption(f"Last modified: {mod_time}")

    with col2:
        st.markdown(f"**Default Config:**  \n`{default_config_path}`")
        if default_config_path.exists():
            st.caption("Used as template for new projects")
