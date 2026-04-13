%% CONN Batch Script - Longitudinal fMRI Preprocessing and Connectivity Analysis
%
% This script creates a CONN project for the longitudinal walking study:
% - 24 subjects (15 Control, 9 Walking)
% - 2 sessions (Pre/Post)
% - Preprocessing from raw BIDS data (no slice timing - multiband TR=0.8s)
% - aCompCor denoising
% - ROI-to-ROI connectivity with Schaefer 400/200 and DiFuMo 256 atlases
%
% Requirements:
% - Run download_atlases.py first to fetch atlas files
% - SPM12 and CONN toolbox
%
% Usage:
%   conn_batch_longitudinal                    % Run full pipeline (local)
%   conn_batch_longitudinal('setup')           % Setup only (no processing)
%   conn_batch_longitudinal('full', N)         % Run with N parallel jobs
%   conn_batch_longitudinal('full', N, 'profile_name') % Use specific cluster profile
%
% Parallel Options:
%   N = 0       : Local processing (no parallelization)
%   N = 1-24    : Number of parallel jobs (recommended: 4-8)
%   N = Inf     : Maximum parallelization (not recommended)
%
% Author: Generated for longitudinal walking study
% Date: 2025

function conn_batch_longitudinal(mode, parallel_jobs, parallel_profile)

if nargin < 1
    mode = 'full';  % 'full' or 'setup'
end
if nargin < 2
    parallel_jobs = 0;  % Default: local processing
end
if nargin < 3
    parallel_profile = [];  % Use default CONN profile
end

%% ========================================================================
%  CONFIGURATION
%  ========================================================================

% Paths
BASE_DIR = '/Volumes/Work/Work/long';
BIDS_DIR = fullfile(BASE_DIR, 'bids');
ATLAS_DIR = fullfile(BASE_DIR, 'atlases');
CONN_DIR = fullfile(BASE_DIR, 'conn_project');
TOOLS_DIR = fullfile(BASE_DIR, 'tools');

% Add SPM and CONN to path
spm_path = fullfile(TOOLS_DIR, 'spm');
conn_path = fullfile(TOOLS_DIR, 'conn');

if ~exist('spm', 'file')
    addpath(spm_path);
    fprintf('Added SPM to path: %s\n', spm_path);
end
if ~exist('conn', 'file')
    addpath(conn_path);
    fprintf('Added CONN to path: %s\n', conn_path);
end

% Verify dependencies
if ~exist('spm', 'file')
    error('SPM not found. Please check path: %s', spm_path);
end
if ~exist('conn', 'file')
    error('CONN not found. Please check path: %s', conn_path);
end

% Create output directory
if ~exist(CONN_DIR, 'dir')
    mkdir(CONN_DIR);
end

% Acquisition parameters
TR = 0.8;  % seconds (multiband 6)
NVOLUMES = 480;
NSESSIONS = 2;

%% ========================================================================
%  SUBJECT DEFINITION
%  ========================================================================

% Subject IDs and groups from completed_subjects_with_groups.csv
% Control group (n=15)
control_subs = {'sub-033', 'sub-034', 'sub-035', 'sub-036', 'sub-037', ...
                'sub-038', 'sub-039', 'sub-040', 'sub-058', 'sub-059', ...
                'sub-060', 'sub-061', 'sub-062', 'sub-063', 'sub-064'};

% Walking group (n=9)
walking_subs = {'sub-043', 'sub-045', 'sub-046', 'sub-047', 'sub-048', ...
                'sub-052', 'sub-055', 'sub-056', 'sub-057'};

% Combine all subjects
all_subs = [control_subs, walking_subs];
NSUBJECTS = length(all_subs);

% Group vector (1=Control, 2=Walking)
groups = [ones(1, length(control_subs)), 2*ones(1, length(walking_subs))];

fprintf('\n========================================\n');
fprintf('CONN Longitudinal Batch Processing\n');
fprintf('========================================\n');
fprintf('Subjects: %d (%d Control, %d Walking)\n', NSUBJECTS, length(control_subs), length(walking_subs));
fprintf('Sessions: %d\n', NSESSIONS);
fprintf('TR: %.2f s\n', TR);
fprintf('Output: %s\n', CONN_DIR);
if parallel_jobs > 0
    fprintf('Parallel: %d jobs', parallel_jobs);
    if ~isempty(parallel_profile)
        fprintf(' (profile: %s)', parallel_profile);
    end
    fprintf('\n');
else
    fprintf('Parallel: Local processing (no parallelization)\n');
end
fprintf('========================================\n\n');

%% ========================================================================
%  BUILD FILE PATHS
%  ========================================================================

fprintf('Building file paths...\n');

% Initialize cell arrays
functionals = cell(1, NSUBJECTS);
structurals = cell(1, NSUBJECTS);

for nsub = 1:NSUBJECTS
    sub_id = all_subs{nsub};
    functionals{nsub} = cell(1, NSESSIONS);
    structurals{nsub} = cell(1, NSESSIONS);

    for nses = 1:NSESSIONS
        ses_id = sprintf('ses-%02d', nses);

        % Functional file
        func_file = fullfile(BIDS_DIR, sub_id, ses_id, 'func', ...
            sprintf('%s_%s_task-rest_bold.nii.gz', sub_id, ses_id));

        % Structural file (use run-01, except sub-057 ses-02 uses run-02)
        if strcmp(sub_id, 'sub-057') && strcmp(ses_id, 'ses-02')
            % Sub-057 ses-02: use run-02 (run-01 segmentation failed)
            anat_file = fullfile(BIDS_DIR, sub_id, ses_id, 'anat', ...
                sprintf('%s_%s_run-02_T1w.nii.gz', sub_id, ses_id));
        else
            % All other subjects: use run-01
            anat_file = fullfile(BIDS_DIR, sub_id, ses_id, 'anat', ...
                sprintf('%s_%s_run-01_T1w.nii.gz', sub_id, ses_id));
        end

        % Verify files exist
        if ~exist(func_file, 'file')
            warning('Functional file not found: %s', func_file);
        end
        if ~exist(anat_file, 'file')
            warning('Anatomical file not found: %s', anat_file);
        end

        functionals{nsub}{nses} = func_file;
        structurals{nsub}{nses} = anat_file;
    end
end

fprintf('  Found %d subjects x %d sessions\n', NSUBJECTS, NSESSIONS);

%% ========================================================================
%  ATLAS DEFINITIONS
%  ========================================================================

fprintf('Setting up atlases...\n');

% Check atlas files exist
% Note: DiFuMo uses 4D probabilistic maps (256 components in 4th dimension)
atlas_files = {
    fullfile(ATLAS_DIR, 'schaefer400_7net.nii'), ...
    fullfile(ATLAS_DIR, 'schaefer200_7net.nii'), ...
    fullfile(ATLAS_DIR, 'difumo256_4D.nii')
};
atlas_names = {'schaefer400_7net', 'schaefer200_7net', 'difumo256'};

% Label files (CONN format: ROI_NUMBER ROI_LABEL)
atlas_labels = {
    fullfile(ATLAS_DIR, 'schaefer400_7net_conn.txt'), ...
    fullfile(ATLAS_DIR, 'schaefer200_7net_conn.txt'), ...
    fullfile(ATLAS_DIR, 'difumo256_conn.txt')
};

for i = 1:length(atlas_files)
    if ~exist(atlas_files{i}, 'file')
        error('Atlas not found: %s\nRun download_atlases.py first!', atlas_files{i});
    end
end
fprintf('  All atlas files found\n');

%% ========================================================================
%  CONN BATCH STRUCTURE - SETUP
%  ========================================================================

fprintf('Building CONN batch structure...\n');

clear batch;

% Project file
batch.filename = fullfile(CONN_DIR, 'conn_longitudinal.mat');

%% Parallel processing configuration
if parallel_jobs > 0
    batch.parallel.N = parallel_jobs;

    if ~isempty(parallel_profile)
        batch.parallel.profile = parallel_profile;
    end

    % Optional: configure parallelization behavior
    % batch.parallel.immediatereturn = 0;  % Wait for jobs to complete

    fprintf('  Parallel processing: %d jobs\n', parallel_jobs);
else
    batch.parallel.N = 0;  % Local processing
    fprintf('  Processing mode: Local (sequential)\n');
end

% Basic setup
batch.Setup.isnew = 1;
batch.Setup.nsubjects = NSUBJECTS;
batch.Setup.RT = TR;

% Functional and structural files
batch.Setup.functionals = functionals;
batch.Setup.structurals = structurals;

% Analysis types (ROI-to-ROI only for efficiency)
batch.Setup.analyses = [1];  % 1=ROI-to-ROI

% Output units
batch.Setup.analysisunits = 1;  % PSC units

%% ROIs - Custom Atlases
% Schaefer: 3D integer labels (multiplelabels=1)
% DiFuMo: 4D probabilistic maps (multiplelabels=0, dimensions=256)
batch.Setup.rois.names = atlas_names;
batch.Setup.rois.files = atlas_files;
batch.Setup.rois.labels = atlas_labels;       % Label files for meaningful ROI names
batch.Setup.rois.multiplelabels = [1, 1, 0];  % Schaefer=labels, DiFuMo=4D maps
batch.Setup.rois.dimensions = {1, 1, 256};    % Schaefer=mean, DiFuMo=256 components
batch.Setup.rois.mask = [0, 0, 0];            % No grey matter masking (atlases already in GM)

%% Subject groups
batch.Setup.subjects.group_names = {'Control', 'Walking'};
batch.Setup.subjects.groups = groups;

%% Second-level covariates (for later analyses)
batch.Setup.subjects.effect_names = {'AllSubjects', 'Group'};
batch.Setup.subjects.effects{1} = ones(NSUBJECTS, 1);  % Intercept
batch.Setup.subjects.effects{2} = groups';              % Group effect

%% Conditions - resting state (full scan)
batch.Setup.conditions.names = {'rest'};
for nsub = 1:NSUBJECTS
    for nses = 1:NSESSIONS
        batch.Setup.conditions.onsets{1}{nsub}{nses} = 0;
        batch.Setup.conditions.durations{1}{nsub}{nses} = inf;
    end
end

%% ========================================================================
%  PREPROCESSING PIPELINE
%  ========================================================================

% Preprocessing steps (NO slice timing for multiband with short TR)
batch.Setup.preprocessing.steps = {
    'functional_realign&unwarp', ...        % Realignment + motion correction
    'functional_center', ...                 % Center to origin
    'functional_art', ...                    % Artifact detection (outlier scans)
    'structural_center', ...                 % Center structural
    'structural_segment&normalize', ...      % Segment & normalize structural
    'functional_normalize_indirect', ...     % Normalize functional via structural
    'functional_smooth'                      % Spatial smoothing
};

% Preprocessing parameters
batch.Setup.preprocessing.fwhm = 6;                    % 6mm FWHM smoothing
batch.Setup.preprocessing.art_thresholds = [5 0.9];   % Intermediate ART thresholds
                                                       % [global signal z=5, motion=0.9mm]
batch.Setup.preprocessing.coregtomean = 0;             % Use first volume (not mean) for coregistration

%% ========================================================================
%  DENOISING - aCompCor
%  ========================================================================

% Band-pass filter
batch.Denoising.filter = [0.01, 0.1];  % 0.01-0.1 Hz

% Linear detrending
batch.Denoising.detrending = 1;

% Confound regression (aCompCor strategy)
batch.Denoising.confounds.names = {'White Matter', 'CSF', 'realignment', 'scrubbing'};
batch.Denoising.confounds.dimensions = {5, 5, 6, inf};  % 5 WM PCs, 5 CSF PCs, 6 motion params, all scrubbing
batch.Denoising.confounds.deriv = {0, 0, 1, 0};         % First derivatives for motion only

%% ========================================================================
%  FIRST-LEVEL ANALYSIS
%  ========================================================================

batch.Analysis.analysis_number = 1;
batch.Analysis.name = 'ROI2ROI_aCompCor';
batch.Analysis.measure = 1;      % Bivariate correlation
batch.Analysis.weight = 2;       % HRF weighting
batch.Analysis.type = 1;         % ROI-to-ROI only
batch.Analysis.sources = {};     % All ROIs as sources

%% ========================================================================
%  EXECUTION CONTROL
%  ========================================================================

switch lower(mode)
    case 'setup'
        % Setup only - don't run processing
        batch.Setup.done = 0;
        batch.Denoising.done = 0;
        batch.Analysis.done = 0;
        fprintf('\nMode: SETUP ONLY (no processing)\n');

    case 'full'
        % Run all steps
        batch.Setup.done = 1;
        batch.Setup.overwrite = 'Yes';
        batch.Denoising.done = 1;
        batch.Denoising.overwrite = 'Yes';
        batch.Analysis.done = 1;
        batch.Analysis.overwrite = 'Yes';
        fprintf('\nMode: FULL PIPELINE\n');

    otherwise
        error('Unknown mode: %s. Use ''full'' or ''setup''', mode);
end

%% ========================================================================
%  RUN CONN BATCH
%  ========================================================================

fprintf('\n========================================\n');
fprintf('Starting CONN batch processing...\n');
fprintf('========================================\n\n');

% Execute batch
conn_batch(batch);

fprintf('\n========================================\n');
fprintf('CONN batch complete!\n');
fprintf('Project file: %s\n', batch.filename);
fprintf('========================================\n');

% Open CONN GUI if setup only
if strcmpi(mode, 'setup')
    fprintf('\nOpening CONN GUI...\n');
    conn;
    conn('load', batch.filename);
end

end
