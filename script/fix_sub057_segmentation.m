function fix_sub057_segmentation()
% FIX_SUB057_SEGMENTATION - Fix failed segmentation for sub-057 ses-02
%
% Issue: Grey matter segmentation failed (all zeros)
% Solutions: 1) Try run-02 T1w, or 2) Manual realignment, or 3) Exclude subject

addpath('/Volumes/Work/Work/long/tools/spm');

fprintf('\n========================================\n');
fprintf('Fix sub-057 ses-02 Segmentation\n');
fprintf('========================================\n\n');

BIDS_DIR = '/Volumes/Work/Work/long/bids';
sub_dir = fullfile(BIDS_DIR, 'sub-057', 'ses-02', 'anat');

%% Option 1: Try run-02 instead of run-01
fprintf('Option 1: Try run-02 T1w\n');
fprintf('--------------------\n');

run01_file = fullfile(sub_dir, 'sub-057_ses-02_run-01_T1w.nii.gz');
run02_file = fullfile(sub_dir, 'sub-057_ses-02_run-02_T1w.nii.gz');

if ~exist(run02_file, 'file')
    fprintf('❌ Run-02 file not found: %s\n', run02_file);
    fprintf('   Proceeding to Option 2\n\n');
else
    fprintf('✓ Run-02 file exists\n');
    fprintf('  Attempting segmentation with run-02...\n\n');

    % Gunzip run-02 if needed
    if ~exist(fullfile(sub_dir, 'sub-057_ses-02_run-02_T1w.nii'), 'file')
        gunzip(run02_file, sub_dir);
    end

    run02_nii = fullfile(sub_dir, 'sub-057_ses-02_run-02_T1w.nii');

    % Center the image
    fprintf('  Step 1: Centering run-02...\n');
    spm_center_image(run02_nii);

    centered_file = fullfile(sub_dir, 'csub-057_ses-02_run-02_T1w.nii');

    % Run segmentation
    fprintf('  Step 2: Running segmentation...\n');
    try
        matlabbatch{1}.spm.spatial.preproc.channel.vols = {[centered_file ',1']};
        matlabbatch{1}.spm.spatial.preproc.channel.biasreg = 0.001;
        matlabbatch{1}.spm.spatial.preproc.channel.biasfwhm = 60;
        matlabbatch{1}.spm.spatial.preproc.channel.write = [0 0];

        % Tissue classes (GM, WM, CSF)
        for i = 1:3
            matlabbatch{1}.spm.spatial.preproc.tissue(i).tpm = {...
                fullfile(spm('Dir'), 'tpm', sprintf('TPM.nii,%d', i))};
            matlabbatch{1}.spm.spatial.preproc.tissue(i).ngaus = [1 1 2];
            matlabbatch{1}.spm.spatial.preproc.tissue(i).native = [1 0];
            matlabbatch{1}.spm.spatial.preproc.tissue(i).warped = [1 0];
        end

        matlabbatch{1}.spm.spatial.preproc.warp.mrf = 1;
        matlabbatch{1}.spm.spatial.preproc.warp.cleanup = 1;
        matlabbatch{1}.spm.spatial.preproc.warp.reg = [0 0.001 0.5 0.05 0.2];
        matlabbatch{1}.spm.spatial.preproc.warp.affreg = 'mni';
        matlabbatch{1}.spm.spatial.preproc.warp.fwhm = 0;
        matlabbatch{1}.spm.spatial.preproc.warp.samp = 3;
        matlabbatch{1}.spm.spatial.preproc.warp.write = [1 1];

        spm_jobman('run', matlabbatch);

        fprintf('  ✓ Segmentation complete\n\n');

        % Check if GM file has data
        gm_file = fullfile(sub_dir, 'wc1csub-057_ses-02_run-02_T1w.nii');
        if exist(gm_file, 'file')
            V = spm_vol(gm_file);
            Y = spm_read_vols(V);
            if max(Y(:)) > 0
                fprintf('  ✓ SUCCESS: Run-02 segmentation has valid GM data!\n');
                fprintf('    Max GM probability: %.3f\n', max(Y(:)));
                fprintf('    Voxels > 0.1: %d\n\n', sum(Y(:) > 0.1));

                fprintf('Next step: Update CONN project to use run-02 for sub-057 ses-02\n');
                return;
            else
                fprintf('  ❌ Run-02 also failed (all zeros)\n\n');
            end
        end
    catch ME
        fprintf('  ❌ Segmentation error: %s\n\n', ME.message);
    end
end

%% Option 2: Manual realignment of run-01
fprintf('Option 2: Manual Realignment (Interactive)\n');
fprintf('--------------------\n');
fprintf('This requires manual intervention in SPM GUI:\n');
fprintf('  1. spm fmri\n');
fprintf('  2. Display → %s\n', run01_file);
fprintf('  3. Reorient → Manually align to AC-PC line\n');
fprintf('  4. Re-run this script\n\n');

%% Option 3: Exclude this subject/session
fprintf('Option 3: Exclude sub-057 ses-02\n');
fprintf('--------------------\n');
fprintf('Analysis would continue with:\n');
fprintf('  - sub-057 ses-01: ✓ (Pre intervention)\n');
fprintf('  - sub-057 ses-02: ✗ (Excluded)\n');
fprintf('  - n = 23 subjects with complete data (instead of 24)\n\n');

fprintf('========================================\n');
fprintf('Recommendation\n');
fprintf('========================================\n');
fprintf('1. Try Option 1 first (run-02) - automated\n');
fprintf('2. If that fails, use Option 3 (exclude) - simplest\n');
fprintf('3. Option 2 (manual) only if you need this session\n\n');

fprintf('To exclude sub-057 ses-02 and continue:\n');
fprintf('  → Modify batch script to skip this session\n');
fprintf('  → Or continue with 47/48 sessions (23 complete subjects)\n\n');

end

function spm_center_image(P)
    % Center image to origin
    V = spm_vol(P);
    Y = spm_read_vols(V);

    % Compute center of mass
    [x,y,z] = ind2sub(size(Y), find(Y > mean(Y(:))));
    com = V.mat * [mean(x); mean(y); mean(z); 1];

    % Create centered transformation
    M = spm_get_space(P);
    M(1:3,4) = M(1:3,4) - com(1:3);

    % Apply
    spm_get_space(P, M);

    fprintf('    Centered to: [%.1f, %.1f, %.1f]\n', com(1), com(2), com(3));
end
