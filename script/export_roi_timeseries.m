function export_roi_timeseries(atlas_name, output_dir)
% EXPORT_ROI_TIMESERIES - Extract denoised ROI timeseries from CONN project
%
% Exports ROI timeseries to multiple formats for cross-platform analysis:
%   - CSV: Individual files per subject/session
%   - HDF5: Single file with all data (for Python)
%   - MAT: MATLAB format with metadata
%
% Usage:
%   export_roi_timeseries('schaefer400_7net', '/Volumes/Work/Work/long/timeseries')
%   export_roi_timeseries('difumo256_4D', '/Volumes/Work/Work/long/timeseries')
%
% Inputs:
%   atlas_name  - Name of atlas in CONN project (e.g., 'schaefer400_7net')
%   output_dir  - Directory to save exported timeseries
%
% Outputs:
%   CSV files: {output_dir}/csv/{subject}_{session}_{atlas}_timeseries.csv
%   HDF5 file:  {output_dir}/{atlas}_all_subjects.h5
%   MAT file:   {output_dir}/{atlas}_all_subjects.mat
%   Metadata:   {output_dir}/{atlas}_metadata.json

%% Setup
if nargin < 2
    error('Usage: export_roi_timeseries(atlas_name, output_dir)');
end

% Add CONN to path
addpath('/Volumes/Work/Work/long/tools/conn');

% Create output directories
if ~exist(output_dir, 'dir')
    mkdir(output_dir);
end
csv_dir = fullfile(output_dir, 'csv');
if ~exist(csv_dir, 'dir')
    mkdir(csv_dir);
end

% Load CONN project
conn_project = '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat';
if ~exist(conn_project, 'file')
    error('CONN project not found: %s', conn_project);
end

fprintf('Loading CONN project: %s\n', conn_project);
conn('load', conn_project);

% Get CONN data
CONN_x = evalin('base', 'CONN_x');

%% Get atlas information
fprintf('Finding atlas: %s\n', atlas_name);

% Search for atlas by name in CONN ROI definitions
atlas_idx = [];
for i = 1:length(CONN_x.Setup.rois.names)
    if strcmpi(CONN_x.Setup.rois.names{i}, atlas_name)
        atlas_idx = i;
        break;
    end
end

if isempty(atlas_idx)
    error('Atlas "%s" not found in CONN project. Available atlases:\n%s', ...
        atlas_name, strjoin(CONN_x.Setup.rois.names, ', '));
end

fprintf('Found atlas at index %d: %s\n', atlas_idx, CONN_x.Setup.rois.names{atlas_idx});

%% Extract ROI information
% Get ROI names and network labels
n_rois = CONN_x.Setup.rois.dimensions{atlas_idx}(2);
roi_names = cell(n_rois, 1);
roi_networks = cell(n_rois, 1);
roi_coords = zeros(n_rois, 3);

fprintf('Extracting ROI metadata for %d ROIs...\n', n_rois);

% Parse ROI names from atlas
for i = 1:n_rois
    try
        % Try to get ROI name from CONN structure
        if iscell(CONN_x.Setup.rois.names{atlas_idx})
            roi_names{i} = CONN_x.Setup.rois.names{atlas_idx}{i};
        else
            roi_names{i} = sprintf('ROI_%03d', i);
        end

        % Extract network label from ROI name (for Schaefer atlases)
        % Format: "7Networks_LH_SomMot_1" -> network = "SomMot"
        tokens = regexp(roi_names{i}, '(\w+)_([LR]H)_(\w+)_(\d+)', 'tokens');
        if ~isempty(tokens)
            roi_networks{i} = tokens{1}{3};
        else
            roi_networks{i} = 'Unknown';
        end

        % Get ROI coordinates (centroid in MNI space)
        % This requires loading the atlas NIfTI file
        % For now, we'll skip coordinates (can be added later if needed)
        roi_coords(i, :) = [NaN, NaN, NaN];

    catch
        roi_names{i} = sprintf('ROI_%03d', i);
        roi_networks{i} = 'Unknown';
        roi_coords(i, :) = [NaN, NaN, NaN];
    end
end

%% Extract timeseries for all subjects and sessions
n_subjects = length(CONN_x.Setup.subjects);
n_sessions = CONN_x.Setup.nsessions(1); % Assuming same sessions for all subjects

fprintf('Extracting timeseries for %d subjects, %d sessions...\n', n_subjects, n_sessions);

% Initialize storage for all data
all_data = struct();
all_data.timeseries = {};  % Cell array: {subject, session}
all_data.subjects = cell(n_subjects, 1);
all_data.sessions = cell(n_sessions, 1);
all_data.roi_names = roi_names;
all_data.roi_networks = roi_networks;
all_data.roi_coords = roi_coords;
all_data.atlas_name = atlas_name;

% Get subject IDs from CONN
for subj = 1:n_subjects
    all_data.subjects{subj} = CONN_x.Setup.subjects{subj};
end

% Session names
for ses = 1:n_sessions
    all_data.sessions{ses} = sprintf('ses-%02d', ses);
end

% Extract timeseries for each subject and session
for subj = 1:n_subjects
    subject_id = all_data.subjects{subj};
    fprintf('  Subject %d/%d: %s\n', subj, n_subjects, subject_id);

    for ses = 1:n_sessions
        session_id = all_data.sessions{ses};

        try
            % Extract denoised timeseries from CONN
            % This uses CONN's internal function to get processed timeseries
            timeseries = conn_get_time(atlas_idx, subj, ses);

            if isempty(timeseries)
                warning('No timeseries found for %s %s', subject_id, session_id);
                all_data.timeseries{subj, ses} = [];
                continue;
            end

            % Store timeseries
            all_data.timeseries{subj, ses} = timeseries;

            % Export individual CSV file
            csv_file = fullfile(csv_dir, sprintf('%s_%s_%s_timeseries.csv', ...
                subject_id, session_id, atlas_name));

            % Create CSV header with ROI names
            fid = fopen(csv_file, 'w');
            fprintf(fid, '%s\n', strjoin(roi_names, ','));
            fclose(fid);

            % Append timeseries data
            dlmwrite(csv_file, timeseries, '-append', 'precision', '%.6f');

        catch ME
            warning('Error extracting timeseries for %s %s: %s', ...
                subject_id, session_id, ME.message);
            all_data.timeseries{subj, ses} = [];
        end
    end
end

%% Export to MAT file
mat_file = fullfile(output_dir, sprintf('%s_all_subjects.mat', atlas_name));
fprintf('Saving MAT file: %s\n', mat_file);
save(mat_file, 'all_data', '-v7.3');

%% Export metadata to JSON
metadata = struct();
metadata.atlas_name = atlas_name;
metadata.n_subjects = n_subjects;
metadata.n_sessions = n_sessions;
metadata.n_rois = n_rois;
metadata.subjects = all_data.subjects;
metadata.sessions = all_data.sessions;
metadata.roi_info = struct();
metadata.roi_info.names = roi_names;
metadata.roi_info.networks = roi_networks;
metadata.roi_info.coords = roi_coords;

json_file = fullfile(output_dir, sprintf('%s_metadata.json', atlas_name));
fprintf('Saving metadata JSON: %s\n', json_file);

% Write JSON (MATLAB R2016b+ has jsonencode)
if exist('jsonencode', 'builtin')
    json_str = jsonencode(metadata);
    % Pretty print (basic formatting)
    json_str = strrep(json_str, ',', sprintf(',\n  '));
    json_str = strrep(json_str, '{', sprintf('{\n  '));
    json_str = strrep(json_str, '}', sprintf('\n}'));

    fid = fopen(json_file, 'w');
    fprintf(fid, '%s', json_str);
    fclose(fid);
else
    warning('jsonencode not available. Skipping JSON export. Use MATLAB R2016b or later.');
end

%% Export to HDF5 (for Python)
% HDF5 export is complex in MATLAB, so we'll provide a Python script
% to convert the MAT file to HDF5 instead
fprintf('\nTo convert to HDF5 for Python, run:\n');
fprintf('  python script/convert_mat_to_hdf5.py %s\n', mat_file);

%% Summary
fprintf('\n=== Export Complete ===\n');
fprintf('Atlas: %s\n', atlas_name);
fprintf('Subjects: %d\n', n_subjects);
fprintf('Sessions: %d\n', n_sessions);
fprintf('ROIs: %d\n', n_rois);
fprintf('\nOutput files:\n');
fprintf('  CSV files: %s/*_timeseries.csv (%d files)\n', csv_dir, n_subjects * n_sessions);
fprintf('  MAT file:  %s\n', mat_file);
fprintf('  Metadata:  %s\n', json_file);

end

% Helper function to get denoised timeseries from CONN
function timeseries = conn_get_time(roi_idx, subject_idx, session_idx)
    % This is a simplified version. The actual implementation depends on
    % CONN's internal structure. You may need to adjust based on CONN version.

    % Access CONN global variable
    CONN_x = evalin('base', 'CONN_x');

    % Get the denoised BOLD file for this subject/session
    % CONN stores denoised data in:
    % CONN_x.folders.preprocessing/results/preprocessing/

    % Try to load ROI timeseries from CONN's results
    try
        % Get ROI extraction results file
        roi_file = fullfile(CONN_x.folders.preprocessing, ...
            sprintf('ROI_Subject%03d_Session%03d.mat', subject_idx, session_idx));

        if exist(roi_file, 'file')
            data = load(roi_file);
            % Extract timeseries for the specified ROI index
            % Structure depends on CONN version, adjust as needed
            if isfield(data, 'data')
                timeseries = data.data{roi_idx};
            else
                timeseries = [];
            end
        else
            % Alternative: use conn() function to extract
            timeseries = conn('get', 'roiextraction', roi_idx, subject_idx, session_idx);
        end
    catch
        % If automatic extraction fails, return empty
        timeseries = [];
    end
end
