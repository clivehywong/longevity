%% CONN Batch Script - RESUME MODE
%
% This script resumes CONN processing from where it left off.
% Use this to:
% - Resume interrupted preprocessing
% - Add parallelization to existing project
% - Skip already-completed steps
%
% Usage:
%   conn_batch_resume                       % Resume with no parallelization
%   conn_batch_resume(4)                    % Resume with 4 parallel jobs
%   conn_batch_resume(8, 'cluster_profile') % Resume with 8 jobs on cluster
%
% IMPORTANT: This assumes conn_longitudinal.mat already exists

function conn_batch_resume(parallel_jobs, parallel_profile)

if nargin < 1
    parallel_jobs = 0;
end
if nargin < 2
    parallel_profile = [];
end

%% Paths
CONN_DIR = '/Volumes/Work/Work/long/conn_project';
PROJECT_FILE = fullfile(CONN_DIR, 'conn_longitudinal.mat');

% Check if project exists
if ~exist(PROJECT_FILE, 'file')
    error(['Project not found: %s\n' ...
           'Run conn_batch_longitudinal(''setup'') first!'], PROJECT_FILE);
end

fprintf('\n========================================\n');
fprintf('CONN Resume Mode\n');
fprintf('========================================\n');
fprintf('Project: %s\n', PROJECT_FILE);
if parallel_jobs > 0
    fprintf('Parallel: %d jobs\n', parallel_jobs);
else
    fprintf('Parallel: Local (sequential)\n');
end
fprintf('========================================\n\n');

%% Build batch structure for resuming
clear batch;

batch.filename = PROJECT_FILE;

%% Parallel configuration
if parallel_jobs > 0
    batch.parallel.N = parallel_jobs;
    if ~isempty(parallel_profile)
        batch.parallel.profile = parallel_profile;
    end
end

%% Resume preprocessing
% overwrite='No' means CONN will skip already-completed steps
batch.Setup.done = 1;
batch.Setup.overwrite = 'No';  % Skip completed preprocessing steps

batch.Denoising.done = 1;
batch.Denoising.overwrite = 'No';  % Skip completed denoising

batch.Analysis.done = 1;
batch.Analysis.overwrite = 'No';  % Skip completed analyses

%% Run
fprintf('Resuming CONN processing...\n');
fprintf('(Skipping already-completed steps)\n\n');

conn_batch(batch);

fprintf('\n========================================\n');
fprintf('Resume complete!\n');
fprintf('========================================\n');

end
