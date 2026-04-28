#!/usr/bin/env python3
"""
Connectivity Configuration Loader

Loads and validates the connectivity_config.yaml file to manage atlas-seed
combinations, prevent combinatorial explosions, and ensure reproducible paths
across the analysis pipeline.

Usage:
    from config_loader import load_config, get_valid_seeds, get_output_path
    
    config = load_config()
    seeds = get_valid_seeds(atlas='DiFuMo256')
    output_path = get_output_path(
        analysis_type='seed_based',
        subject_id='033',
        session='01',
        atlas='DiFuMo256',
        seed='Motor_Cortex'
    )
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


class ConfigLoadError(Exception):
    """Raised when configuration cannot be loaded or is invalid."""
    pass


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


class ConnectivityConfig:
    """
    Manager for connectivity analysis configuration.
    
    Loads from YAML and provides typed access to configuration sections,
    with validation and helpful error messages.
    """
    
    # Default config path relative to project root
    DEFAULT_CONFIG_PATH = ".github/connectivity_config.yaml"
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.
        
        Parameters
        ----------
        config_path : str, optional
            Path to connectivity_config.yaml. If None, searches for it
            relative to the project root.
        """
        self.config_path = self._find_config(config_path)
        self.config = self._load_yaml()
        self._validate_config()
        
    def _find_config(self, config_path: Optional[str]) -> str:
        """Find the configuration file."""
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise ConfigLoadError(f"Config file not found: {config_path}")
            return str(path.absolute())
        
        # Try relative to current directory
        if Path(self.DEFAULT_CONFIG_PATH).exists():
            return str(Path(self.DEFAULT_CONFIG_PATH).absolute())
        
        # Try relative to project root (find .git directory)
        for parent in Path.cwd().parents:
            potential_path = parent / self.DEFAULT_CONFIG_PATH
            if potential_path.exists():
                return str(potential_path.absolute())
        
        raise ConfigLoadError(
            f"Config file not found. Searched for {self.DEFAULT_CONFIG_PATH} "
            "starting from current directory and moving up to project root."
        )
    
    def _load_yaml(self) -> Dict:
        """Load YAML configuration file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            if not config:
                raise ConfigLoadError(f"Config file is empty: {self.config_path}")
            return config
        except yaml.YAMLError as e:
            raise ConfigLoadError(f"Invalid YAML in {self.config_path}: {e}")
        except IOError as e:
            raise ConfigLoadError(f"Cannot read {self.config_path}: {e}")
    
    def _validate_config(self):
        """Validate configuration structure and content."""
        errors = []
        
        # Check required top-level sections
        required_sections = ['atlases', 'seeds', 'valid_combinations', 
                            'preprocessing', 'hpc', 'output']
        for section in required_sections:
            if section not in self.config:
                errors.append(f"Missing required section: {section}")
        
        if errors:
            raise ConfigValidationError(
                f"Configuration validation failed:\n" + "\n".join(errors)
            )
        
        # Validate atlases
        self._validate_atlases()
        
        # Validate seeds
        self._validate_seeds()
        
        # Validate valid_combinations
        self._validate_valid_combinations()
    
    def _validate_atlases(self):
        """Validate atlas definitions."""
        errors = []
        atlases = self.config.get('atlases', {})
        
        if not atlases:
            errors.append("No atlases defined")
            
        for atlas_name, atlas_def in atlases.items():
            if not isinstance(atlas_def, dict):
                errors.append(f"Atlas '{atlas_name}' definition is not a dict")
                continue
            
            required_fields = ['name', 'space', 'resolution_mm']
            for field in required_fields:
                if field not in atlas_def:
                    errors.append(
                        f"Atlas '{atlas_name}' missing required field: {field}"
                    )
        
        if errors:
            raise ConfigValidationError(
                "Atlas validation failed:\n" + "\n".join(errors)
            )
    
    def _validate_seeds(self):
        """Validate seed definitions."""
        errors = []
        seeds = self.config.get('seeds', {})
        valid_atlases = set(self.config.get('atlases', {}).keys())
        
        if not seeds:
            errors.append("No seeds defined")
            return
        
        seed_names = set()
        for seed_name, seed_def in seeds.items():
            if not isinstance(seed_def, dict):
                errors.append(f"Seed '{seed_name}' definition is not a dict")
                continue
            
            # Check for duplicates
            if seed_name in seed_names:
                errors.append(f"Duplicate seed name: {seed_name}")
            seed_names.add(seed_name)
            
            # Required fields
            required_fields = ['region', 'coordinates_mni', 'radius_mm', 'valid_atlases']
            for field in required_fields:
                if field not in seed_def:
                    errors.append(
                        f"Seed '{seed_name}' missing required field: {field}"
                    )
                    
            # Validate valid_atlases references
            if 'valid_atlases' in seed_def:
                for atlas in seed_def['valid_atlases']:
                    if atlas not in valid_atlases:
                        errors.append(
                            f"Seed '{seed_name}' references unknown atlas: {atlas}"
                        )
        
        if errors:
            raise ConfigValidationError(
                "Seed validation failed:\n" + "\n".join(errors)
            )
    
    def _validate_valid_combinations(self):
        """Validate valid_combinations section."""
        errors = []
        combinations = self.config.get('valid_combinations', {})
        seeds = set(self.config.get('seeds', {}).keys())
        
        for category, seed_list in combinations.items():
            if not isinstance(seed_list, list):
                errors.append(
                    f"valid_combinations.{category} is not a list"
                )
                continue
            
            for seed in seed_list:
                if seed not in seeds:
                    errors.append(
                        f"valid_combinations.{category} references unknown seed: {seed}"
                    )
        
        if errors:
            raise ConfigValidationError(
                "Valid combinations validation failed:\n" + "\n".join(errors)
            )
    
    def get_atlases(self) -> Dict[str, Dict]:
        """Get all atlas definitions."""
        return self.config.get('atlases', {})
    
    def get_atlas(self, atlas_name: str) -> Dict:
        """
        Get specific atlas definition.
        
        Parameters
        ----------
        atlas_name : str
            Name of atlas (e.g., 'DiFuMo256')
            
        Returns
        -------
        dict
            Atlas definition
            
        Raises
        ------
        KeyError
            If atlas not found
        """
        atlases = self.get_atlases()
        if atlas_name not in atlases:
            available = ', '.join(atlases.keys())
            raise KeyError(
                f"Atlas '{atlas_name}' not found. Available: {available}"
            )
        return atlases[atlas_name]
    
    def get_seeds(self) -> Dict[str, Dict]:
        """Get all seed definitions."""
        return self.config.get('seeds', {})
    
    def get_seed(self, seed_name: str) -> Dict:
        """
        Get specific seed definition.
        
        Parameters
        ----------
        seed_name : str
            Name of seed (e.g., 'Motor_Cortex')
            
        Returns
        -------
        dict
            Seed definition
            
        Raises
        ------
        KeyError
            If seed not found
        """
        seeds = self.get_seeds()
        if seed_name not in seeds:
            available = ', '.join(sorted(seeds.keys()))
            raise KeyError(
                f"Seed '{seed_name}' not found. Available: {available}"
            )
        return seeds[seed_name]
    
    def get_valid_seeds(
        self, 
        atlas: Optional[str] = None,
        network: Optional[str] = None
    ) -> List[str]:
        """
        Get list of valid seeds, optionally filtered by atlas or network.
        
        Parameters
        ----------
        atlas : str, optional
            Filter to seeds valid for this atlas
        network : str, optional
            Filter to seeds in this network
            
        Returns
        -------
        list of str
            Valid seed names
            
        Examples
        --------
        >>> seeds = config.get_valid_seeds(atlas='DiFuMo256')
        >>> motor_seeds = config.get_valid_seeds(network='Motor')
        """
        seeds_dict = self.get_seeds()
        valid_seeds = []
        
        for seed_name, seed_def in seeds_dict.items():
            # Check atlas filter
            if atlas:
                if atlas not in seed_def.get('valid_atlases', []):
                    continue
            
            # Check network filter
            if network:
                if network not in seed_def.get('networks', []):
                    continue
            
            valid_seeds.append(seed_name)
        
        return sorted(valid_seeds)
    
    def get_valid_combination(self, seed: str, atlas: str) -> bool:
        """
        Check if seed-atlas combination is valid.
        
        Parameters
        ----------
        seed : str
            Seed name
        atlas : str
            Atlas name
            
        Returns
        -------
        bool
            True if combination is valid
            
        Examples
        --------
        >>> if config.get_valid_combination('Motor_Cortex', 'DiFuMo256'):
        ...     print("Valid combination")
        """
        try:
            seed_def = self.get_seed(seed)
            return atlas in seed_def.get('valid_atlases', [])
        except KeyError:
            return False
    
    def get_preprocessing(self) -> Dict:
        """Get preprocessing parameters."""
        return self.config.get('preprocessing', {})
    
    def get_hpc(self) -> Dict:
        """Get HPC configuration."""
        return self.config.get('hpc', {})
    
    def get_output_config(self) -> Dict:
        """Get output configuration."""
        return self.config.get('output', {})
    
    def get_validation_config(self) -> Dict:
        """Get validation configuration."""
        return self.config.get('validation', {})
    
    def get_metadata(self) -> Dict:
        """Get study metadata."""
        return self.config.get('metadata', {})
    
    def get_output_path(
        self,
        analysis_type: str,
        subject_id: Optional[str] = None,
        session: Optional[str] = None,
        atlas: Optional[str] = None,
        seed: Optional[str] = None,
        level: str = 'session'
    ) -> str:
        """
        Generate output path for analysis results.
        
        Parameters
        ----------
        analysis_type : str
            Type of analysis ('seed_based', 'local_measures', 'network_connectivity')
        subject_id : str, optional
            Subject ID (e.g., '033')
        session : str, optional
            Session ID (e.g., '01')
        atlas : str, optional
            Atlas name (e.g., 'DiFuMo256')
        seed : str, optional
            Seed name (e.g., 'Motor_Cortex')
        level : str
            'session' for subject-level, 'group' for group-level
            
        Returns
        -------
        str
            Output directory path
            
        Examples
        --------
        >>> path = config.get_output_path(
        ...     analysis_type='seed_based',
        ...     subject_id='033',
        ...     session='01',
        ...     atlas='DiFuMo256',
        ...     seed='Motor_Cortex'
        ... )
        >>> # Returns: 'results/seed_based/DiFuMo256/Motor_Cortex/sub-033_ses-01/'
        """
        output_cfg = self.get_output_config()
        base = output_cfg.get('base', 'results')
        
        # Get appropriate pattern based on level and analysis type
        if level == 'session':
            patterns = output_cfg.get('session_level', {})
        else:
            patterns = output_cfg.get('group_level', {})
        
        if analysis_type not in patterns:
            available = ', '.join(patterns.keys())
            raise ValueError(
                f"Unknown analysis type '{analysis_type}'. Available: {available}"
            )
        
        pattern = patterns[analysis_type].get('pattern', '')
        if not pattern:
            raise ValueError(
                f"No output pattern defined for {level} {analysis_type}"
            )
        
        # Format pattern with variables
        format_vars = {
            'base': base,
            'atlas_name': atlas or '',
            'seed_name': seed or '',
            'subject_id': subject_id or '',
            'session': session or '',
        }
        
        return pattern.format(**format_vars)
    
    def get_output_files(
        self,
        analysis_type: str,
        level: str = 'session'
    ) -> List[str]:
        """
        Get expected output files for an analysis type.
        
        Parameters
        ----------
        analysis_type : str
            Type of analysis
        level : str
            'session' for subject-level, 'group' for group-level
            
        Returns
        -------
        list of str
            Expected output file patterns
            
        Examples
        --------
        >>> files = config.get_output_files('seed_based')
        >>> # Returns: ['*_zmap.nii.gz', '*_zmap_fdr.nii.gz', ...]
        """
        output_cfg = self.get_output_config()
        
        if level == 'session':
            patterns = output_cfg.get('session_level', {})
        else:
            patterns = output_cfg.get('group_level', {})
        
        if analysis_type not in patterns:
            return []
        
        return patterns[analysis_type].get('files', [])
    
    def print_summary(self):
        """Print summary of configuration."""
        print("\n" + "="*70)
        print("CONNECTIVITY CONFIGURATION SUMMARY")
        print("="*70)
        
        # Atlases
        atlases = self.get_atlases()
        print(f"\nAtlases ({len(atlases)}):")
        for name, cfg in atlases.items():
            print(f"  • {name}: {cfg.get('name', 'N/A')}")
            print(f"    Resolution: {cfg.get('resolution_mm', 'N/A')}mm")
        
        # Seeds
        seeds = self.get_seeds()
        print(f"\nSeeds ({len(seeds)}):")
        networks = {}
        for name, cfg in seeds.items():
            for net in cfg.get('networks', []):
                if net not in networks:
                    networks[net] = []
                networks[net].append(name)
        
        for network in sorted(networks.keys()):
            print(f"  {network} ({len(networks[network])} seeds):")
            for seed in sorted(networks[network]):
                print(f"    • {seed}")
        
        # Preprocessing
        preproc = self.get_preprocessing()
        print(f"\nPreprocessing:")
        print(f"  High-pass: {preproc.get('high_pass_hz', 'N/A')} Hz")
        print(f"  Low-pass: {preproc.get('low_pass_hz', 'N/A')} Hz")
        print(f"  Smoothing: {preproc.get('smoothing_fwhm_mm', 'N/A')} mm FWHM")
        
        print("\n" + "="*70 + "\n")


def load_config(config_path: Optional[str] = None) -> ConnectivityConfig:
    """
    Load connectivity configuration.
    
    Parameters
    ----------
    config_path : str, optional
        Path to config file. If None, searches for it automatically.
        
    Returns
    -------
    ConnectivityConfig
        Loaded configuration object
        
    Raises
    ------
    ConfigLoadError
        If config cannot be loaded
    ConfigValidationError
        If config is invalid
        
    Examples
    --------
    >>> config = load_config()
    >>> seeds = config.get_valid_seeds(atlas='DiFuMo256')
    """
    return ConnectivityConfig(config_path)


def validate_config(config_path: Optional[str] = None) -> Tuple[bool, List[str]]:
    """
    Validate configuration file.
    
    Parameters
    ----------
    config_path : str, optional
        Path to config file
        
    Returns
    -------
    tuple of (bool, list)
        (is_valid, error_messages)
        
    Examples
    --------
    >>> is_valid, errors = validate_config()
    >>> if not is_valid:
    ...     print("\\n".join(errors))
    """
    try:
        config = load_config(config_path)
        return True, []
    except (ConfigLoadError, ConfigValidationError) as e:
        return False, str(e).split("\n")


if __name__ == '__main__':
    # Command-line interface
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Connectivity configuration manager'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate configuration file'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Print configuration summary'
    )
    parser.add_argument(
        '--seeds',
        action='store_true',
        help='List all seeds'
    )
    parser.add_argument(
        '--get-seeds',
        metavar='ATLAS',
        help='Get valid seeds for an atlas'
    )
    parser.add_argument(
        '--check-combo',
        nargs=2,
        metavar=('SEED', 'ATLAS'),
        help='Check if seed-atlas combination is valid'
    )
    parser.add_argument(
        '--output-path',
        nargs='+',
        help='Generate output path (analysis_type subject session atlas seed)'
    )
    parser.add_argument(
        '--config',
        help='Path to configuration file'
    )
    
    args = parser.parse_args()
    
    try:
        config = load_config(args.config)
        
        if args.validate:
            print("✓ Configuration is valid")
            
        if args.summary:
            config.print_summary()
            
        if args.seeds:
            print("All seeds:")
            for seed in sorted(config.get_valid_seeds()):
                print(f"  • {seed}")
            
        if args.get_seeds:
            seeds = config.get_valid_seeds(atlas=args.get_seeds)
            print(f"Seeds valid for {args.get_seeds}:")
            for seed in seeds:
                print(f"  • {seed}")
            
        if args.check_combo:
            seed, atlas = args.check_combo
            is_valid = config.get_valid_combination(seed, atlas)
            status = "✓ VALID" if is_valid else "✗ INVALID"
            print(f"{status}: {seed} × {atlas}")
            
        if args.output_path:
            parts = args.output_path
            if len(parts) < 1:
                print("Error: output_path requires at least analysis_type")
            else:
                kwargs = {'analysis_type': parts[0]}
                if len(parts) > 1:
                    kwargs['subject_id'] = parts[1]
                if len(parts) > 2:
                    kwargs['session'] = parts[2]
                if len(parts) > 3:
                    kwargs['atlas'] = parts[3]
                if len(parts) > 4:
                    kwargs['seed'] = parts[4]
                path = config.get_output_path(**kwargs)
                print(f"Output path: {path}")
        
    except (ConfigLoadError, ConfigValidationError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
